"""Integridad de las 9 tablas raw y de la suciedad sembrada.

La suciedad se comprueba explícitamente porque tiene que **seguir ahí**: si un
refactor la limpiara sin querer, los modelos de staging y sus tests dejarían de
tener algo que resolver y el repo perdería la mitad de su gracia.
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from generator.cli import TABLE_ORDER


def test_all_nine_tables_exist(tables):
    assert set(tables) == set(TABLE_ORDER)
    assert len(TABLE_ORDER) == 9


def test_no_table_is_empty(tables):
    for name, df in tables.items():
        assert len(df) > 0, f"{name} salió vacía"


def test_no_column_is_untyped(tables):
    """Ninguna columna puede quedar en dtype Object.

    Es fácil que ocurra sin querer: `np.where(mask, texto, None)` devuelve un
    array de object y polars lo importa como Object. Esa columna no se puede
    comparar, ni ordenar, ni serializar a Parquet.
    """
    offenders = [
        f"{name}.{col}"
        for name, df in tables.items()
        for col, dtype in df.schema.items()
        if dtype == pl.Object
    ]
    assert not offenders, f"columnas sin tipo: {offenders}"


def test_tables_survive_a_parquet_roundtrip(tables, tmp_path):
    """Lo que no sobreviva a Parquet nunca llegará a Postgres."""
    for name, df in tables.items():
        path = tmp_path / f"{name}.parquet"
        df.write_parquet(path)
        assert pl.read_parquet(path).equals(df), f"{name} no sobrevivió el roundtrip"


@pytest.mark.parametrize(
    ("child", "column", "parent", "key"),
    [
        ("orders", "customer_id", "customers", "customer_id"),
        ("order_items", "order_id", "orders", "order_id"),
        ("order_items", "product_id", "products", "product_id"),
        ("deliveries", "order_id", "orders", "order_id"),
        ("tickets", "order_id", "orders", "order_id"),
        ("survey_responses", "invitation_id", "survey_invitations", "invitation_id"),
    ],
)
def test_referential_integrity(tables, child, column, parent, key):
    """La suciedad ensucia atributos, nunca las llaves."""
    orphans = tables[child].join(tables[parent], left_on=column, right_on=key, how="anti")
    assert len(orphans) == 0, f"{child}.{column} tiene {len(orphans)} huérfanos"


def test_every_response_belongs_to_an_invitation(tables):
    assert len(tables["survey_responses"]) < len(tables["survey_invitations"])


def test_no_refill_orders_after_cancellation(tables):
    """El corazón del loop mensual: nadie resurte un plan que ya canceló.

    Si esto falla, la simulación dejó de ser causal y el análisis de churn
    estaría midiendo un artefacto del generador.
    """
    cancelled = tables["subscriptions"].filter(pl.col("fecha_cancelacion").is_not_null())
    offending = (
        tables["orders"]
        .filter(pl.col("tipo") == "resurtido")
        .join(cancelled, on="customer_id")
        .filter(pl.col("fecha_pedido") > pl.col("fecha_cancelacion"))
    )
    assert len(offending) == 0


def test_failed_deliveries_have_no_delivery_date(tables):
    """La demora se calcula, no viene dada: sin fecha no hay demora."""
    failed = tables["deliveries"].filter(pl.col("estatus") == "fallida")
    assert len(failed) > 0
    assert failed["fecha_entrega"].null_count() == len(failed)


def test_refill_ces_is_only_triggered_by_completed_deliveries(tables):
    """El CES de resurtido mide recibirlo, así que la entrega tuvo que ocurrir.

    Es el mismo criterio que el NPS transaccional. Sin filtrar, la invitación
    saldría fechada con el día en que el pedido habría llegado y apuntaría a una
    entrega que la propia tabla de hechos declara inexistente.
    """
    failed = tables["deliveries"].filter(pl.col("estatus") == "fallida").select("order_id")
    ces = tables["survey_invitations"].filter(pl.col("tipo") == "ces_resurtido")
    assert len(ces) > 0
    offending = ces.join(failed, left_on="id_evento_disparador", right_on="order_id")
    assert offending.is_empty(), f"{len(offending)} invitaciones sobre entregas fallidas"


def test_duplicate_customers_were_seeded(tables, cfg):
    """Mismo humano, dos ids: staging tendrá que deduplicar."""
    customers = tables["customers"]
    # El email normalizado delata al duplicado: se quita el alias con "+" y los
    # puntos de la parte local, que no cambian el buzón real. El motor de regex
    # de polars no soporta look-ahead, así que la parte local se aísla partiendo
    # por la arroba en vez de mirar hacia adelante.
    normalized = (
        customers["email"]
        .str.to_lowercase()
        .str.replace_all(r"\+[^@]*", "")
        .str.split("@")
        .list.first()
        .str.replace_all(r"\.", "")
    )
    duplicated = len(normalized) - normalized.n_unique()
    expected = cfg["dirt"]["duplicate_customers"]["rate"] * len(customers)
    assert duplicated > expected * 0.4


def test_call_center_csat_arrives_on_the_wrong_scale(tables):
    """La trampa más jugosa: 1-10 donde el resto manda 1-5."""
    csat = (
        tables["survey_responses"]
        .join(tables["survey_invitations"], on="invitation_id")
        .filter((pl.col("tipo") == "csat_ticket") & pl.col("score").is_between(1, 10))
    )
    call_center = csat.filter(pl.col("canal") == "call_center")
    otros = csat.filter(pl.col("canal") != "call_center")

    assert call_center["score"].max() > 5
    assert otros["score"].max() <= 5


def test_out_of_range_scores_were_seeded(tables, cfg):
    values = cfg["dirt"]["out_of_range_scores"]["values"]
    scores = tables["survey_responses"]["score"]
    assert scores.is_in(values).sum() > 0


def test_test_accounts_were_seeded(tables):
    emails = tables["customers"]["email"]
    assert emails.str.contains(r"@farmapato\.test|^qa\+|^prueba_").sum() > 0


def test_timestamps_arrive_in_mixed_formats(tables):
    """Tres sistemas fuente, tres formatos de hora, una sola columna de texto."""
    created = tables["tickets"]["created_at"]
    assert created.str.ends_with("Z").sum() > 0
    assert created.str.contains(r"-06:00$").sum() > 0
    assert (~created.str.contains(r"Z$|-06:00$")).sum() > 0


def test_verbatim_is_mostly_null(tables, cfg):
    """Por diseño, no por suciedad: casi nadie escribe el comentario."""
    responses = tables["survey_responses"]
    null_share = responses["verbatim"].null_count() / len(responses)
    assert null_share == pytest.approx(cfg["dirt"]["nulls"]["verbatim"], abs=0.06)


def test_stockout_crisis_shows_up_in_the_affected_city(tables, cfg):
    """El episodio narrativo tiene que verse en los datos, no sólo en el README."""
    crisis = cfg["stockout_crisis"]
    start = crisis["start_date"]
    end = start + dt.timedelta(weeks=crisis["duration_weeks"])

    items = (
        tables["order_items"]
        .join(tables["orders"], on="order_id")
        .join(tables["customers"], on="customer_id")
        .join(tables["products"], on="product_id")
        .filter(pl.col("categoria").str.starts_with("cronicos"))
        .with_columns(agotado=pl.col("fill_status") == "agotado")
    )
    during = items.filter(
        (pl.col("ciudad") == crisis["city"]) & pl.col("fecha_pedido").is_between(start, end)
    )["agotado"].mean()
    baseline = items.filter(
        (pl.col("ciudad") != crisis["city"]) & pl.col("fecha_pedido").is_between(start, end)
    )["agotado"].mean()

    assert during > baseline * 2, f"quiebre en crisis {during:.3%} vs {baseline:.3%}"
