"""Ensamblado de las 9 tablas raw.

Las columnas van **en español y sin acentos**, como las escribiría el ERP de una
farmacia mexicana. `raw` emula los sistemas fuente, así que normalizar nombres al
inglés es trabajo de staging en dbt, no del generador.

Aquí también se traducen los índices internos (ciudad 0, canal 2, fill_status 3)
a las etiquetas de texto que tendría un sistema real.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from .operations import DELIVERY_ENTREGADA
from .population import NEVER, Customers, Products
from .simulate import Accumulator, stack

# Días entre el ordinal 1 (0001-01-01) y la época Unix.
EPOCH_ORDINAL = 719163

FILL_LABELS = np.array(["completo", "parcial", "sustituido", "agotado"])
DELIVERY_LABELS = np.array(["entregada", "fallida"])

# Verbatims plantilla. No son el objeto de este proyecto —el análisis de texto
# es el Proyecto 2— pero un literal repetido se vería falso en el dashboard.
VERBATIMS_NEGATIVE = np.array(
    [
        "Llevo dos semanas esperando mi medicamento.",
        "Otra vez me llego incompleto el pedido.",
        "Me cambiaron la marca sin avisarme.",
        "El repartidor nunca llego y nadie me aviso.",
        "Pesimo servicio, ya voy a cancelar el plan.",
        "Nadie contesta en soporte.",
    ]
)
VERBATIMS_POSITIVE = np.array(
    [
        "Todo perfecto, llego antes de lo prometido.",
        "Muy buen servicio y buen precio.",
        "El plan me facilita mucho la vida.",
        "Excelente atencion del repartidor.",
        "Rapido y sin complicaciones.",
        "Me encanta no tener que ir a la farmacia.",
    ]
)


def _to_date(ordinals: np.ndarray) -> np.ndarray:
    return (np.asarray(ordinals) - EPOCH_ORDINAL).astype("datetime64[D]")


def _to_datetime(ordinals: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Fecha + hora del día. Los sistemas fuente no guardan sólo la fecha."""
    ordinals = np.asarray(ordinals)
    seconds = (ordinals - EPOCH_ORDINAL) * 86400 + rng.integers(0, 86400, size=len(ordinals))
    # polars sólo acepta resoluciones ms/us/ns al convertir desde numpy.
    return seconds.astype("datetime64[s]").astype("datetime64[us]")


def _nullable_date(ordinals: np.ndarray) -> pl.Series:
    """Fechas con NULL donde el sentinel dice 'nunca ocurrió'."""
    ordinals = np.asarray(ordinals)
    never = np.flatnonzero(ordinals >= NEVER)
    safe = np.where(ordinals >= NEVER, EPOCH_ORDINAL, ordinals)
    return pl.Series(_to_date(safe)).scatter(never, None)


def _nullable_int(values: np.ndarray) -> pl.Series:
    """Enteros con NULL donde el centinela negativo dice 'no aplica'."""
    values = np.asarray(values)
    return pl.Series(np.maximum(values, 0), dtype=pl.Int64).scatter(
        np.flatnonzero(values < 0), None
    )


def _nullable_str(values: np.ndarray, keep: np.ndarray) -> pl.Series:
    """Texto con NULL donde `keep` es falso.

    Se construye tipado a propósito: `np.where(mask, texto, None)` produce un
    array de object, que polars importa como dtype Object en vez de String — y
    una columna Object no se puede comparar ni escribir a Parquet.
    """
    return pl.Series(values, dtype=pl.String).scatter(np.flatnonzero(~keep), None)


def _verbatims(responses: dict[str, np.ndarray], rng: np.random.Generator) -> pl.Series:
    """Comentario para quien escribió; NULL para el resto (la gran mayoría)."""
    n = len(responses["score"])
    # El tono del comentario acompaña al score dentro de su propia escala.
    tops = {"nps": 8, "csat": 4, "ces": 5}
    threshold = np.array([tops[s] for s in responses["scale"]])
    positive = responses["score"] >= threshold
    text = np.where(
        positive,
        rng.choice(VERBATIMS_POSITIVE, size=n),
        rng.choice(VERBATIMS_NEGATIVE, size=n),
    )
    return _nullable_str(text, responses["has_verbatim"])


def build_tables(
    cfg: dict[str, Any],
    acc: Accumulator,
    cust: Customers,
    prods: Products,
    rng: np.random.Generator,
) -> dict[str, pl.DataFrame]:
    city_names = np.array([c["name"] for c in cfg["geography"]["cities"]])
    chan_names = np.array(list(cfg["channels"]["distribution"]))
    cat_names = np.array([c["name"] for c in cfg["catalog"]["categories"]])
    cond_names = np.array(list(cfg["subscriptions"]["conditions"]))
    reason_names = np.array(cfg["subscriptions"]["cancellation_reasons"])
    ticket_cats = np.array(list(cfg["operations"]["tickets"]["categories"]))

    orders = stack(acc.orders)
    items = stack(acc.items)
    deliveries = stack(acc.deliveries)
    tickets = stack(acc.tickets)
    invitations = stack(acc.invitations)
    responses = stack(acc.responses)

    has_sub = cust.has_sub
    sub_idx = np.flatnonzero(has_sub)

    tables = {
        "customers": pl.DataFrame(
            {
                "customer_id": cust.customer_id,
                "nombre_completo": cust.full_name,
                "email": cust.email,
                "fecha_alta": _to_date(cust.signup_ord),
                "ciudad": city_names[cust.city],
                "anio_nacimiento": cust.birth_year,
                "canal_adquisicion": cust.acquisition_channel,
                "canal_preferido": chan_names[cust.preferred_channel],
            }
        ),
        "products": pl.DataFrame(
            {
                "product_id": prods.product_id,
                "categoria": cat_names[prods.category],
                "precio": prods.price,
                "requiere_receta": prods.requires_prescription,
            }
        ),
        "subscriptions": pl.DataFrame(
            {
                "subscription_id": cust.customer_id[sub_idx],
                "customer_id": cust.customer_id[sub_idx],
                "condicion": cond_names[cust.sub_condition[sub_idx]],
                "fecha_inicio": _to_date(cust.sub_start_ord[sub_idx]),
                "fecha_cancelacion": _nullable_date(cust.sub_cancel_ord[sub_idx]),
                "motivo_cancelacion": _nullable_str(
                    reason_names[np.maximum(cust.sub_reason[sub_idx], 0)],
                    cust.sub_reason[sub_idx] >= 0,
                ),
                "valor_mensual": cust.sub_monthly_value[sub_idx],
                "frecuencia": np.where(cust.sub_bimonthly[sub_idx], "bimestral", "mensual"),
            }
        ),
        "orders": pl.DataFrame(
            {
                "order_id": orders["order_id"],
                "customer_id": orders["customer_id"],
                "fecha_pedido": _to_date(orders["order_ord"]),
                "canal": chan_names[orders["channel"]],
                "tipo": np.where(orders["is_refill"], "resurtido", "transaccional"),
                "monto": np.round(orders["amount"], 2),
            }
        ),
        "order_items": pl.DataFrame(
            {
                "order_id": items["order_id"],
                "product_id": items["product_id"],
                "cantidad": items["quantity"],
                "fill_status": FILL_LABELS[items["fill_status"]],
            }
        ),
        "deliveries": pl.DataFrame(
            {
                "delivery_id": np.arange(1, len(deliveries["order_id"]) + 1),
                "order_id": deliveries["order_id"],
                "fecha_prometida": _to_date(deliveries["promised_ord"]),
                # La entrega fallida no tiene fecha de entrega: la demora se
                # calcula en dbt, no viene dada.
                "fecha_entrega": pl.Series(_to_date(deliveries["delivered_ord"])).scatter(
                    np.flatnonzero(deliveries["status"] != DELIVERY_ENTREGADA), None
                ),
                "estatus": DELIVERY_LABELS[deliveries["status"]],
            }
        ),
        "tickets": pl.DataFrame(
            {
                "ticket_id": tickets["ticket_id"],
                "customer_id": tickets["customer_id"],
                "order_id": tickets["order_id"],
                "categoria": ticket_cats[tickets["category"]],
                "canal": chan_names[tickets["channel"]],
                "created_at": _to_datetime(tickets["created_ord"], rng),
                "resolved_at": _to_datetime(
                    tickets["created_ord"] + np.ceil(tickets["resolution_hours"] / 24), rng
                ),
            }
        ),
        "survey_invitations": pl.DataFrame(
            {
                "invitation_id": invitations["invitation_id"],
                "customer_id": invitations["customer_id"],
                "tipo": invitations["touchpoint"],
                # El NPS relacional no lo dispara ningún evento: va nulo. Tiene
                # que ser un entero nulable, no un float con NaN — un NaN no es
                # igual a sí mismo y rompería cualquier comparación aguas abajo.
                "id_evento_disparador": _nullable_int(invitations["trigger_event_id"]),
                "fecha_envio": _to_datetime(invitations["sent_ord"], rng),
                "canal": invitations["channel"],
            }
        ),
        "survey_responses": pl.DataFrame(
            {
                "invitation_id": responses["invitation_id"],
                "fecha_respuesta": _to_datetime(responses["responded_ord"], rng),
                "score": responses["score"],
                "verbatim": _verbatims(responses, rng),
            }
        ),
    }
    return tables
