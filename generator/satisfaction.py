"""De la operación a la satisfacción latente.

Los eventos operativos golpean una variable continua sin unidad, calibrada para
que 0 sea un cliente neutro y una desviación estándar sea 1.0. La jerarquía de
los golpes es deliberada (quiebre en crónico >> entrega tardía > ticket lento >
precio) y vive entera en `config.yaml`.

**Memoria de eventos.** El efecto decae con la vida media del config y se olvida
al cerrarse su ventana. Como el simulador avanza mes a mes, la memoria se guarda
como casillas mensuales —con los valores actuales, el impacto de este mes, el
del anterior y el del trasanterior— y los pesos salen de `config.memory_weights`.
La ventana queda exacta; la resolución del decay dentro del mes es la
aproximación que este generador acepta a cambio de poder vectorizar todo.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .config import memory_weights
from .operations import DELIVERY_FALLIDA, FILL_AGOTADO, FILL_PARCIAL, FILL_SUSTITUIDO, MonthOps
from .population import Customers, Products

# Percentil de monto a partir del cual el cliente percibe el pedido como caro.
PRICE_PERCEPTION_PERCENTILE = 75


def _delivery_effect(cfg: dict[str, Any], delay_days: np.ndarray) -> np.ndarray:
    """Logística invertida: medio día de retraso no se nota, dos días sí.

    efecto(d) = max_effect / (1 + exp(-steepness * (d - threshold)))
    """
    dd = cfg["operational_effects"]["delivery_delay"]
    return dd["max_effect"] / (1 + np.exp(-dd["steepness"] * (delay_days - dd["threshold_days"])))


def monthly_impact(
    cfg: dict[str, Any], ops: MonthOps, cust: Customers, prods: Products
) -> np.ndarray:
    """Impacto operativo del mes sobre cada cliente del padrón."""
    eff = cfg["operational_effects"]
    n_orders = len(ops.order_cust)
    n_cust = len(cust)

    # ---- Disponibilidad, a nivel ítem y resumido a nivel pedido ------------
    item_chronic = prods.is_chronic[ops.item_product]
    item_effect = np.zeros(len(ops.item_fill))
    agotado = ops.item_fill == FILL_AGOTADO
    item_effect[agotado] = np.where(
        item_chronic[agotado], eff["stockout_chronic"], eff["stockout_otc"]
    )
    item_effect[ops.item_fill == FILL_PARCIAL] = eff["partial_fill"]
    item_effect[ops.item_fill == FILL_SUSTITUIDO] = eff["substitution"]

    # Por pedido se toma el peor ítem, no la suma: el pedido salió bien o salió
    # mal. Sumar tres líneas agotadas daría un golpe de 2.5 SD, fuera de escala.
    fill_effect = np.zeros(n_orders)
    np.minimum.at(fill_effect, ops.item_order_pos, item_effect)

    # ---- Entrega -----------------------------------------------------------
    order_has_chronic = np.zeros(n_orders, dtype=bool)
    np.logical_or.at(order_has_chronic, ops.item_order_pos, item_chronic)

    delivery_effect = _delivery_effect(cfg, ops.delay_days)
    dd = cfg["operational_effects"]["delivery_delay"]
    delivery_effect = np.where(
        order_has_chronic, delivery_effect * dd["chronic_multiplier"], delivery_effect
    )
    # La entrega fallida duele como el peor retraso posible.
    delivery_effect = np.where(
        ops.delivery_status == DELIVERY_FALLIDA,
        dd["max_effect"] * np.where(order_has_chronic, dd["chronic_multiplier"], 1.0),
        delivery_effect,
    )

    # ---- Precio percibido --------------------------------------------------
    # Débil a propósito: el hallazgo del proyecto NO es precio. Se dispara en
    # los pedidos caros del mes, que es cuando el cliente lo nota.
    price_effect = np.zeros(n_orders)
    if n_orders:
        umbral = np.percentile(ops.order_amount, PRICE_PERCEPTION_PERCENTILE)
        price_effect[ops.order_amount > umbral] = eff["price_perception"]

    order_effect = fill_effect + delivery_effect + price_effect

    # ---- Soporte lento -----------------------------------------------------
    tr = eff["ticket_resolution"]
    extra_days = np.maximum(ops.ticket_resolution_hours - tr["tolerated_hours"], 0) / 24
    ticket_effect = np.maximum(extra_days * tr["effect_per_extra_day"], tr["cap"])

    impact = np.bincount(ops.order_cust, weights=order_effect, minlength=n_cust)
    impact += np.bincount(ops.ticket_cust, weights=ticket_effect, minlength=n_cust)
    return impact


def roll_memory(cust: Customers, impact: np.ndarray) -> None:
    """Desplaza la memoria un mes y mete el impacto recién ocurrido."""
    cust.impact[:, 1:] = cust.impact[:, :-1]
    cust.impact[:, 0] = impact


def latent(
    cfg: dict[str, Any], cust: Customers, idx: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Satisfacción latente de unos clientes en este momento, con ruido."""
    memory = cust.impact[idx] @ memory_weights(cfg)
    noise = rng.normal(0, cfg["latent_satisfaction"]["transient_noise_sd"], size=len(idx))
    return cust.latent_base[idx] + memory + noise
