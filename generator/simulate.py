"""El loop mensual: donde se resuelve la causalidad del churn.

Satisfacción, cancelación y pedidos futuros son mutuamente dependientes: no se
puede generar toda la historia de pedidos y calcular el churn después, porque
saldrían resurtidos de gente que ya se había ido. La simulación avanza mes a
mes —24 iteraciones— y dentro de cada mes todo es NumPy vectorizado sobre el
padrón entero. Así el churn queda causalmente correcto por construcción, sin
ningún paso de poda posterior.

Orden dentro del mes: altas → operación → impacto en la latente → encuestas →
cancelaciones. Las encuestas ven el estado ya golpeado por la operación del mes,
y las cancelaciones ven ese mismo estado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import churn, satisfaction, surveys
from .config import Rngs, days_in_month, month_starts
from .operations import DELIVERY_ENTREGADA, MonthOps, simulate_month
from .population import (
    NEVER,
    Customers,
    Products,
    build_name_catalog,
    build_products,
    concat_customers,
    new_cohort,
)

# Cadencia del NPS relacional: una ola cada tres meses, a todo el padrón activo.
RELATIONAL_WAVE_EVERY = 3

# Historia previa al periodo simulado: los clientes iniciales no se dieron de
# alta todos el mismo día.
INITIAL_SIGNUP_SPREAD_DAYS = 730


@dataclass
class Accumulator:
    """Filas de cada mes; se concatenan una sola vez al final."""

    orders: list[dict[str, np.ndarray]] = field(default_factory=list)
    items: list[dict[str, np.ndarray]] = field(default_factory=list)
    deliveries: list[dict[str, np.ndarray]] = field(default_factory=list)
    tickets: list[dict[str, np.ndarray]] = field(default_factory=list)
    invitations: list[dict[str, np.ndarray]] = field(default_factory=list)
    responses: list[dict[str, np.ndarray]] = field(default_factory=list)


@dataclass
class Counters:
    """Ids globales: las tablas se ensamblan al final pero los ids son únicos."""

    order: int = 1
    ticket: int = 1
    invitation: int = 1


def _store_operations(
    acc: Accumulator,
    ops: MonthOps,
    cust: Customers,
    prods: Products,
    counters: Counters,
) -> tuple[np.ndarray, np.ndarray]:
    """Vuelca las tablas operativas del mes. Devuelve (order_ids, ticket_ids)."""
    n_orders, n_tickets = len(ops.order_cust), len(ops.ticket_cust)
    order_id = np.arange(counters.order, counters.order + n_orders)
    ticket_id = np.arange(counters.ticket, counters.ticket + n_tickets)
    counters.order += n_orders
    counters.ticket += n_tickets

    acc.orders.append(
        {
            "order_id": order_id,
            "customer_id": cust.customer_id[ops.order_cust],
            "order_ord": ops.order_ord,
            "channel": ops.order_channel,
            "is_refill": ops.order_is_refill,
            "amount": ops.order_amount,
        }
    )
    acc.items.append(
        {
            "order_id": order_id[ops.item_order_pos],
            "product_id": prods.product_id[ops.item_product],
            "quantity": ops.item_qty,
            "fill_status": ops.item_fill,
        }
    )
    acc.deliveries.append(
        {
            "order_id": order_id,
            "promised_ord": ops.promised_ord,
            "delivered_ord": ops.delivered_ord,
            "status": ops.delivery_status,
        }
    )
    acc.tickets.append(
        {
            "ticket_id": ticket_id,
            "customer_id": cust.customer_id[ops.ticket_cust],
            "order_id": order_id[ops.ticket_order_pos],
            "category": ops.ticket_category,
            "channel": ops.ticket_channel,
            "created_ord": ops.ticket_created_ord,
            "resolution_hours": ops.ticket_resolution_hours,
        }
    )
    return order_id, ticket_id


def _emit_survey(
    acc: Accumulator,
    cfg: dict[str, Any],
    rng: np.random.Generator,
    cust: Customers,
    counters: Counters,
    touchpoint: str,
    scale: str,
    cust_idx: np.ndarray,
    trigger_id: np.ndarray,
    sent_ord: np.ndarray,
) -> None:
    """Genera las invitaciones de un touchpoint y las respuestas que produzcan."""
    if len(cust_idx) == 0:
        return

    tp = cfg["surveys"]["touchpoints"][touchpoint]
    share = tp.get("sample_share", 1.0)
    if share < 1.0:
        # No se encuesta cada evento: fatiga del encuestado.
        keep = rng.random(len(cust_idx)) < share
        cust_idx, trigger_id, sent_ord = cust_idx[keep], trigger_id[keep], sent_ord[keep]

    n = len(cust_idx)
    invitation_id = np.arange(counters.invitation, counters.invitation + n)
    counters.invitation += n

    # El canal de envío lo fija el touchpoint (email el relacional, app el
    # transaccional); donde el config no lo fija, manda el preferido del cliente.
    chan_names = np.array(list(cfg["channels"]["distribution"]))
    channel = (
        np.full(n, tp["channel"])
        if "channel" in tp
        else chan_names[cust.preferred_channel[cust_idx]]
    )

    acc.invitations.append(
        {
            "invitation_id": invitation_id,
            "customer_id": cust.customer_id[cust_idx],
            "touchpoint": np.full(n, touchpoint),
            "trigger_event_id": trigger_id,
            "sent_ord": sent_ord,
            "channel": channel,
        }
    )

    lat = satisfaction.latent(cfg, cust, cust_idx, rng)
    answered = surveys.respond_mask(cfg, rng, touchpoint, lat, cust.preferred_channel[cust_idx])
    score = surveys.score_from_latent(cfg, scale, lat[answered])
    acc.responses.append(
        {
            "invitation_id": invitation_id[answered],
            "responded_ord": sent_ord[answered] + surveys.response_lag_days(cfg, rng, len(score)),
            "score": score,
            "has_verbatim": surveys.verbatim_mask(cfg, rng, score, scale),
            # El canal preferido se arrastra porque el CSAT del call center
            # llega en escala 1-10; lo aplica dirt.py.
            "customer_channel": cust.preferred_channel[cust_idx][answered],
            "scale": np.full(len(score), scale),
            "touchpoint": np.full(len(score), touchpoint),
        }
    )


def _emit_month_surveys(
    acc: Accumulator,
    cfg: dict[str, Any],
    rng: np.random.Generator,
    cust: Customers,
    counters: Counters,
    ops: MonthOps,
    order_id: np.ndarray,
    ticket_id: np.ndarray,
    month_ord: int,
    month_index: int,
) -> None:
    delivered = np.flatnonzero(ops.delivery_status == DELIVERY_ENTREGADA)
    resolved_ord = ops.ticket_created_ord + np.ceil(ops.ticket_resolution_hours / 24).astype(
        np.int64
    )
    billing = ops.ticket_category == list(cfg["operations"]["tickets"]["categories"]).index(
        "facturacion"
    )
    # El CES de resurtido mide el esfuerzo de *recibir* el resurtido, así que lo
    # dispara la entrega realizada, no el pedido. Una entrega fallida no tiene
    # fecha de entrega en la tabla de hechos: la invitación quedaría fechada con
    # el día en que el pedido habría llegado, apuntando a un evento que no pasó.
    refill = np.flatnonzero(ops.order_is_refill & (ops.delivery_status == DELIVERY_ENTREGADA))

    # NPS relacional: ola trimestral por email a todo el padrón activo. No lo
    # dispara un evento, por eso su trigger va nulo (-1).
    if month_index % RELATIONAL_WAVE_EVERY == 0:
        wave = np.flatnonzero(cust.active_on(month_ord))
        _emit_survey(
            acc,
            cfg,
            rng,
            cust,
            counters,
            "nps_relacional",
            "nps",
            wave,
            np.full(len(wave), -1),
            np.full(len(wave), month_ord + 1),
        )

    _emit_survey(
        acc,
        cfg,
        rng,
        cust,
        counters,
        "nps_transaccional",
        "nps",
        ops.order_cust[delivered],
        order_id[delivered],
        ops.delivered_ord[delivered],
    )
    _emit_survey(
        acc,
        cfg,
        rng,
        cust,
        counters,
        "csat_ticket",
        "csat",
        ops.ticket_cust,
        ticket_id,
        resolved_ord,
    )
    _emit_survey(
        acc,
        cfg,
        rng,
        cust,
        counters,
        "ces_resurtido",
        "ces",
        ops.order_cust[refill],
        order_id[refill],
        ops.delivered_ord[refill],
    )
    _emit_survey(
        acc,
        cfg,
        rng,
        cust,
        counters,
        "ces_facturacion",
        "ces",
        ops.ticket_cust[billing],
        ticket_id[billing],
        resolved_ord[billing],
    )


def run(cfg: dict[str, Any]) -> tuple[Accumulator, Customers, Products]:
    """Corre los 24 meses y devuelve todo lo generado."""
    rngs = Rngs(cfg["meta"]["seed"])
    prods = build_products(cfg, rngs.get("products"))
    names = build_name_catalog(cfg["meta"]["seed"])

    months = month_starts(cfg)
    start_ord = months[0].toordinal()

    # Padrón inicial: sus altas son anteriores al periodo simulado.
    rng_pop = rngs.get("population")
    n0 = cfg["scale"]["initial_customers"]
    cust = new_cohort(
        cfg,
        rng_pop,
        names,
        n0,
        1,
        start_ord - rng_pop.integers(1, INITIAL_SIGNUP_SPREAD_DAYS, size=n0),
    )
    next_customer_id = n0 + 1

    acc, counters = Accumulator(), Counters()
    growth = cfg["scale"]["monthly_growth_rate"]

    for m, first_day in enumerate(months):
        month_ord = first_day.toordinal()
        n_days = days_in_month(first_day)

        if m > 0:
            n_new = int(round(n0 * (1 + growth) ** (m - 1) * growth))
            signup = month_ord + rng_pop.integers(0, n_days, size=n_new)
            cust = concat_customers(
                cust, new_cohort(cfg, rng_pop, names, n_new, next_customer_id, signup)
            )
            next_customer_id += n_new

        ops = simulate_month(
            cfg, rngs.get("operations"), cust, prods, month_ord, n_days, first_day.month
        )
        order_id, ticket_id = _store_operations(acc, ops, cust, prods, counters)

        satisfaction.roll_memory(cust, satisfaction.monthly_impact(cfg, ops, cust, prods))

        _emit_month_surveys(
            acc, cfg, rngs.get("surveys"), cust, counters, ops, order_id, ticket_id, month_ord, m
        )

        # ---- Cancelaciones, a fin de mes -----------------------------------
        end_ord = month_ord + n_days - 1
        active = np.flatnonzero(cust.sub_active_on(end_ord))
        rng_ch = rngs.get("churn")
        cancels, reason = churn.cancellations(
            cfg, rng_ch, satisfaction.latent(cfg, cust, active, rng_ch)
        )
        idx = active[cancels]
        cust.sub_cancel_ord[idx] = end_ord
        cust.sub_reason[idx] = reason[cancels]
        # Cancelar el Plan no es irse de FarmaPato: una parte sigue comprando
        # transaccional. El resto deja de aparecer en los pedidos.
        stays = rng_ch.random(len(idx)) < cfg["churn"]["post_churn_transactional_rate"]
        cust.inactive_ord[idx[~stays]] = end_ord

    return acc, cust, prods


def stack(rows: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    """Concatena las filas mensuales en una sola tabla."""
    if not rows:
        return {}
    return {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}


def is_never(ordinals: np.ndarray) -> np.ndarray:
    return ordinals >= NEVER
