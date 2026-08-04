"""Métricas del bloque `expected` del config, calculadas sobre las tablas raw.

Esto es **código de test**, no la capa analítica: las métricas de negocio del
proyecto viven en los marts de dbt. Aquí sólo se recalcula lo justo para
comprobar que el modelo generativo sigue calibrado.

Antes de medir hay que deshacer la suciedad sembrada, igual que hará staging: si
se midiera sobre los datos crudos, la escala 1-10 del call center y los valores
centinela moverían las métricas y el test estaría validando la suciedad en vez
del modelo causal.
"""

from __future__ import annotations

from typing import Any

import polars as pl

CHURN_WINDOW_DAYS = 90


def _clean_nps(tables: dict[str, pl.DataFrame], touchpoint: str) -> pl.DataFrame:
    """Respuestas de un touchpoint NPS, sin los valores fuera de rango."""
    return (
        tables["survey_responses"]
        .join(tables["survey_invitations"], on="invitation_id")
        .filter(pl.col("tipo") == touchpoint)
        .filter(pl.col("score").is_between(0, 10))
    )


def nps(tables: dict[str, pl.DataFrame], cfg: dict[str, Any]) -> float:
    """NPS = %promotores − %detractores, en puntos."""
    scales = cfg["surveys"]["scales"]["nps"]
    df = _clean_nps(tables, "nps_relacional")
    promoters = (df["score"] >= scales["promoter_min"]).mean()
    detractors = (df["score"] <= scales["detractor_max"]).mean()
    return (promoters - detractors) * 100


def detractor_share(tables: dict[str, pl.DataFrame], cfg: dict[str, Any]) -> float:
    df = _clean_nps(tables, "nps_relacional")
    return (df["score"] <= cfg["surveys"]["scales"]["nps"]["detractor_max"]).mean()


def csat_top2box(tables: dict[str, pl.DataFrame], cfg: dict[str, Any]) -> float:
    """% top-2-box del CSAT, deshaciendo la escala 1-10 del call center."""
    mismatch = cfg["dirt"]["call_center_scale_mismatch"]
    df = (
        tables["survey_responses"]
        .join(tables["survey_invitations"], on="invitation_id")
        .filter(pl.col("tipo") == "csat_ticket")
        # El proveedor del call center manda 1-10: se devuelve a 1-5 antes de
        # medir, que es justo lo que tendrá que hacer staging.
        .with_columns(
            score=pl.when(pl.col("canal") == mismatch["channel"])
            .then(((pl.col("score") - 1) * 4 / 9 + 1).round())
            .otherwise(pl.col("score"))
        )
        .filter(pl.col("score").is_between(1, 5))
    )
    return (df["score"] >= cfg["surveys"]["scales"]["csat"]["top_box_min"]).mean()


def churn_ratio_detractor_vs_promoter(
    tables: dict[str, pl.DataFrame], cfg: dict[str, Any]
) -> float:
    """Churn a 90 días por categoría NPS, sobre suscriptores del Plan Resurtido.

    Es el hallazgo central del proyecto y la razón de ser del bloque `expected`:
    si la calibración se rompe, este número lo delata.
    """
    scales = cfg["surveys"]["scales"]["nps"]
    df = (
        _clean_nps(tables, "nps_relacional")
        .join(tables["subscriptions"], on="customer_id")
        # Sólo cuenta quien tenía el Plan vivo cuando contestó.
        .filter(
            (pl.col("fecha_inicio") <= pl.col("fecha_respuesta").dt.date())
            & (
                pl.col("fecha_cancelacion").is_null()
                | (pl.col("fecha_cancelacion") > pl.col("fecha_respuesta").dt.date())
            )
        )
        .with_columns(
            categoria=pl.when(pl.col("score") >= scales["promoter_min"])
            .then(pl.lit("promotor"))
            .when(pl.col("score") <= scales["detractor_max"])
            .then(pl.lit("detractor"))
            .otherwise(pl.lit("pasivo")),
            churned=(
                pl.col("fecha_cancelacion").is_not_null()
                & (
                    (pl.col("fecha_cancelacion") - pl.col("fecha_respuesta").dt.date())
                    .dt.total_days()
                    .le(CHURN_WINDOW_DAYS)
                )
            ),
        )
        .group_by("categoria")
        .agg(pl.col("churned").mean())
    )
    rates = dict(zip(df["categoria"], df["churned"], strict=True))
    return rates["detractor"] / rates["promotor"]


def subscription_revenue_share(tables: dict[str, pl.DataFrame], _cfg: dict[str, Any]) -> float:
    orders = tables["orders"]
    return orders.filter(pl.col("tipo") == "resurtido")["monto"].sum() / orders["monto"].sum()


def orders_last_month(tables: dict[str, pl.DataFrame], _cfg: dict[str, Any]) -> float:
    """Pedidos del último mes simulado, transaccionales y de resurtido."""
    orders = tables["orders"]
    last = orders["fecha_pedido"].max()
    return float(
        orders.filter(
            (pl.col("fecha_pedido").dt.year() == last.year)
            & (pl.col("fecha_pedido").dt.month() == last.month)
        ).height
    )


def relational_responses_per_wave(tables: dict[str, pl.DataFrame], _cfg: dict[str, Any]) -> float:
    df = _clean_nps(tables, "nps_relacional")
    n_waves = df["fecha_envio"].str.slice(0, 7).n_unique()
    return len(df) / n_waves


CALCULATORS = {
    "nps_relacional_overall": nps,
    "detractor_share": detractor_share,
    "csat_top2box": csat_top2box,
    "churn_ratio_detractor_vs_promoter": churn_ratio_detractor_vs_promoter,
    "subscription_revenue_share": subscription_revenue_share,
    "orders_last_month": orders_last_month,
    "relational_responses_per_wave": relational_responses_per_wave,
}


def expected_metrics(tables: dict[str, pl.DataFrame], cfg: dict[str, Any]) -> dict[str, float]:
    return {name: float(fn(tables, cfg)) for name, fn in CALCULATORS.items()}
