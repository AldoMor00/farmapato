"""Carga real contra Postgres.

Sólo corre con `FARMAPATO_DB_TESTS=1` y la base levantada (`make db-up`); en CI
lo activará el workflow, que tiene Postgres como service container. El resto del
tiempo `make check` no depende de que Docker esté arriba.

Ningún test deja rastro: la fixture hace rollback en vez de commit, y en Postgres
hasta el TRUNCATE es transaccional.
"""

from __future__ import annotations

import os

import polars as pl
import pytest
from adbc_driver_postgresql import dbapi

from loader.load import SCHEMA, TABLES, connection_uri, load

pytestmark = pytest.mark.skipif(
    os.environ.get("FARMAPATO_DB_TESTS") != "1",
    reason="necesita Postgres; exporta FARMAPATO_DB_TESTS=1 con la base levantada",
)

SAMPLE_ROWS = 50


@pytest.fixture
def conn():
    with dbapi.connect(connection_uri()) as connection:
        yield connection
        connection.rollback()


@pytest.fixture(scope="session")
def sample(tmp_path_factory, tables):
    """Un recorte del dataset escrito a Parquet, como lo dejaría el generador."""
    src = tmp_path_factory.mktemp("landing")
    for name in TABLES:
        tables[name].head(SAMPLE_ROWS).write_parquet(src / f"{name}.parquet")
    return src


@pytest.fixture(scope="session")
def expected(tables):
    return {name: min(SAMPLE_ROWS, len(tables[name])) for name in TABLES}


def count(conn, table: str) -> int:
    """Se lee con polars y no con `cursor.fetchone()` a propósito.

    El fetch del DBAPI de ADBC exige PyArrow instalado; `pl.read_database` toma
    el stream de Arrow por PyCapsule y no lo necesita. Escribir tampoco lo
    necesita, así que el paso de carga se queda sin esa dependencia.
    """
    return pl.read_database(f"SELECT count(*) AS n FROM {SCHEMA}.{table}", conn).item()


def test_load_writes_every_table(conn, sample, expected):
    counts = load(conn, sample)
    assert counts == expected
    for name in TABLES:
        assert count(conn, name) == expected[name]


def test_load_is_idempotent(conn, sample, expected):
    """El TRUNCATE es lo que hace que `make load` se pueda repetir sin duplicar."""
    assert load(conn, sample) == load(conn, sample) == expected
    assert count(conn, "orders") == expected["orders"]


def test_mixed_timezones_land_as_text(conn, sample):
    """La suciedad llega intacta a `raw`: staging tiene con qué trabajar."""
    load(conn, sample)
    tickets = pl.read_database(f"SELECT created_at FROM {SCHEMA}.tickets", conn)
    assert tickets.schema["created_at"] == pl.String
    assert tickets["created_at"].str.ends_with("Z").any(), "se perdieron los formatos mezclados"
