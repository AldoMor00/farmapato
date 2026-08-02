"""Operación de un mes: pedidos, ítems, entregas y tickets.

Todo lo de aquí es la *causa*; el efecto sobre la satisfacción se calcula en
`satisfaction.py` a partir de estas mismas tablas. Los pedidos referencian al
cliente por su **índice posicional** en el padrón, no por `customer_id`: así el
agregado por cliente es un `bincount` y no un join.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .population import Customers, Products

FILL_COMPLETO, FILL_PARCIAL, FILL_SUSTITUIDO, FILL_AGOTADO = range(4)
DELIVERY_ENTREGADA, DELIVERY_FALLIDA = 0, 1


@dataclass
class MonthOps:
    """Tablas operativas de un mes. Los `*_cust` son índices en el padrón."""

    # orders
    order_cust: np.ndarray
    order_ord: np.ndarray  # fecha del pedido
    order_is_refill: np.ndarray
    order_channel: np.ndarray
    order_amount: np.ndarray

    # order_items (order_pos indexa dentro de este mismo mes)
    item_order_pos: np.ndarray
    item_product: np.ndarray
    item_qty: np.ndarray
    item_fill: np.ndarray

    # deliveries (una por pedido, alineada con orders)
    promised_ord: np.ndarray
    delivered_ord: np.ndarray
    delivery_status: np.ndarray
    delay_days: np.ndarray

    # tickets
    ticket_cust: np.ndarray
    ticket_order_pos: np.ndarray
    ticket_category: np.ndarray
    ticket_channel: np.ndarray
    ticket_created_ord: np.ndarray
    ticket_resolution_hours: np.ndarray


def _crisis_factor(cfg: dict[str, Any], day_ord: np.ndarray) -> np.ndarray:
    """Intensidad de la crisis de desabasto en cada fecha, de 0 a 1.

    Seis semanas a full seguidas de una rampa de recuperación: el reabasto no
    llega de golpe. Se evalúa por fecha de pedido, no por mes completo, porque
    la crisis arranca a mitad de septiembre.
    """
    cr = cfg["stockout_crisis"]
    start = cr["start_date"].toordinal()
    peak_end = start + cr["duration_weeks"] * 7
    recovery_end = peak_end + cr["recovery_weeks"] * 7

    factor = np.zeros(len(day_ord), dtype=float)
    factor[(day_ord >= start) & (day_ord < peak_end)] = 1.0
    tail = (day_ord >= peak_end) & (day_ord < recovery_end)
    factor[tail] = 1.0 - (day_ord[tail] - peak_end) / (recovery_end - peak_end)
    return factor


def simulate_month(
    cfg: dict[str, Any],
    rng: np.random.Generator,
    cust: Customers,
    prods: Products,
    month_start_ord: int,
    n_days: int,
    month_number: int,
) -> MonthOps:
    n_cust = len(cust)
    ops_cfg = cfg["operations"]

    # ---- Pedidos -----------------------------------------------------------
    # Transaccionales: Poisson por cliente activo, con estacionalidad OTC.
    active = cust.active_on(month_start_ord)
    season = cfg["scale"]["seasonality_otc"][month_number]
    lam = cfg["scale"]["transactional_orders_per_customer_month"] * season
    n_trans = rng.poisson(lam * active, size=n_cust)

    # Resurtido: un pedido por suscriptor vigente; los bimestrales, mes de por
    # medio. No lleva estacionalidad — el crónico no elige cuándo enfermarse.
    refill_due = cust.sub_active_on(month_start_ord) & (
        ~cust.sub_bimonthly | (month_number % 2 == 0)
    )

    trans_cust = np.repeat(np.arange(n_cust), n_trans)
    refill_cust = np.flatnonzero(refill_due)
    order_cust = np.concatenate([trans_cust, refill_cust])
    order_is_refill = np.concatenate(
        [np.zeros(len(trans_cust), bool), np.ones(len(refill_cust), bool)]
    )
    n_orders = len(order_cust)

    order_ord = month_start_ord + rng.integers(0, n_days, size=n_orders)
    # El canal del pedido es casi siempre el preferido del cliente.
    n_channels = len(cfg["channels"]["distribution"])
    order_channel = np.where(
        rng.random(n_orders) < 0.88,
        cust.preferred_channel[order_cust],
        rng.integers(0, n_channels, size=n_orders),
    )

    # ---- Líneas del pedido -------------------------------------------------
    basket = ops_cfg["basket"]
    lam_lines = np.where(
        order_is_refill,
        basket["extra_lines_lambda"]["subscription"],
        basket["extra_lines_lambda"]["transactional"],
    )
    n_lines = 1 + rng.poisson(lam_lines)
    item_order_pos = np.repeat(np.arange(n_orders), n_lines)
    n_items = len(item_order_pos)

    # Qué producto: el resurtido saca de la categoría crónica de la condición
    # del paciente; el transaccional casi siempre de las no crónicas.
    chronic_pool = np.flatnonzero(prods.is_chronic)
    other_pool = np.flatnonzero(~prods.is_chronic)
    want_chronic = np.where(
        order_is_refill[item_order_pos],
        True,
        rng.random(n_items) < basket["chronic_share_transactional"],
    )
    item_product = np.where(
        want_chronic,
        rng.choice(chronic_pool, size=n_items),
        rng.choice(other_pool, size=n_items),
    )

    qty_cfg = basket["quantity"]
    item_qty = rng.choice(list(qty_cfg), size=n_items, p=np.array(list(qty_cfg.values()))).astype(
        np.int32
    )

    # fill_status: probabilidades base, agravadas por la crisis en la ciudad y
    # las categorías afectadas.
    fs = ops_cfg["fill_status"]
    p_base = np.array([fs["completo"], fs["parcial"], fs["sustituido"], fs["agotado"]])
    p_stockout = np.full(n_items, p_base[FILL_AGOTADO])

    cr = cfg["stockout_crisis"]
    crisis_city = next(
        i for i, c in enumerate(cfg["geography"]["cities"]) if c["name"] == cr["city"]
    )
    cat_names = [c["name"] for c in cfg["catalog"]["categories"]]
    affected_ids = [cat_names.index(c) for c in cr["affected_categories"]]
    affected_cats = np.isin(prods.category[item_product], affected_ids)
    in_crisis_city = cust.city[order_cust][item_order_pos] == crisis_city
    intensity = _crisis_factor(cfg, order_ord)[item_order_pos]
    hit = affected_cats & in_crisis_city
    p_stockout = np.where(
        hit,
        p_base[FILL_AGOTADO] * (1 + (cr["stockout_rate_multiplier"] - 1) * intensity),
        p_base[FILL_AGOTADO],
    )

    u = rng.random(n_items)
    item_fill = np.full(n_items, FILL_COMPLETO, dtype=np.int8)
    item_fill[u < p_stockout] = FILL_AGOTADO
    rest = u >= p_stockout
    # Entre lo que no se agotó, se reparte parcial y sustituido.
    u2 = rng.random(n_items)
    p_parcial = p_base[FILL_PARCIAL]
    p_sustituido = p_parcial + p_base[FILL_SUSTITUIDO]
    item_fill[rest & (u2 < p_parcial)] = FILL_PARCIAL
    item_fill[rest & (u2 >= p_parcial) & (u2 < p_sustituido)] = FILL_SUSTITUIDO

    # ---- Monto -------------------------------------------------------------
    # El agotado no se cobra; el parcial se cobra a la mitad.
    line_price = prods.price[item_product] * item_qty
    charged = np.where(
        item_fill == FILL_AGOTADO, 0.0, np.where(item_fill == FILL_PARCIAL, 0.5, 1.0)
    )
    gross = np.bincount(item_order_pos, weights=line_price * charged, minlength=n_orders)
    # El resurtido cobra el valor pactado del plan, no la suma de catálogo.
    order_amount = np.where(
        order_is_refill,
        np.nan_to_num(cust.sub_monthly_value[order_cust]),
        np.round(gross, 2),
    )

    # ---- Entregas ----------------------------------------------------------
    dlv = ops_cfg["delivery"]
    base_days = np.array([c["base_delivery_days"] for c in cfg["geography"]["cities"]])
    city_base = base_days[cust.city[order_cust]]
    promised_days = city_base + dlv["promised_days_offset"]
    actual_days = city_base + rng.gamma(dlv["delay_shape"], dlv["delay_scale"], size=n_orders)
    # Durante la crisis hasta el reabasto de emergencia llega tarde.
    actual_days += (
        cr["delivery_delay_extra_days"]
        * _crisis_factor(cfg, order_ord)
        * (cust.city[order_cust] == crisis_city)
    )

    delay_days = actual_days - promised_days
    promised_ord = order_ord + np.ceil(promised_days).astype(np.int64)
    delivered_ord = order_ord + np.ceil(actual_days).astype(np.int64)
    delivery_status = np.where(
        rng.random(n_orders) < dlv["failed_delivery_rate"], DELIVERY_FALLIDA, DELIVERY_ENTREGADA
    ).astype(np.int8)

    # ---- Tickets -----------------------------------------------------------
    tk = ops_cfg["tickets"]
    had_stockout = (
        np.bincount(item_order_pos, weights=(item_fill == FILL_AGOTADO), minlength=n_orders) > 0
    )
    was_late = delay_days > 0
    p_ticket = np.full(n_orders, tk["base_rate_per_order"])
    p_ticket = np.where(was_late, tk["rate_if_late"], p_ticket)
    p_ticket = np.where(had_stockout, tk["rate_if_stockout"], p_ticket)
    p_ticket = np.where(delivery_status == DELIVERY_FALLIDA, tk["rate_if_stockout"], p_ticket)

    has_ticket = rng.random(n_orders) < p_ticket
    ticket_order_pos = np.flatnonzero(has_ticket)
    n_tickets = len(ticket_order_pos)

    cats_tk = tk["categories"]
    res = tk["resolution_hours"]
    return MonthOps(
        order_cust=order_cust,
        order_ord=order_ord,
        order_is_refill=order_is_refill,
        order_channel=order_channel,
        order_amount=order_amount,
        item_order_pos=item_order_pos,
        item_product=item_product,
        item_qty=item_qty,
        item_fill=item_fill,
        promised_ord=promised_ord,
        delivered_ord=delivered_ord,
        delivery_status=delivery_status,
        delay_days=delay_days,
        ticket_cust=order_cust[ticket_order_pos],
        ticket_order_pos=ticket_order_pos,
        ticket_category=rng.choice(
            len(cats_tk), size=n_tickets, p=np.array(list(cats_tk.values()))
        ),
        ticket_channel=order_channel[ticket_order_pos],
        ticket_created_ord=delivered_ord[ticket_order_pos],
        ticket_resolution_hours=rng.gamma(res["shape"], res["scale"], size=n_tickets),
    )
