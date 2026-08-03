"""El DDL de `raw` contra lo que produce el generador.

Este es el test que de verdad importa del paso de carga, y no necesita base de
datos: si alguien añade una columna al generador y olvida el DDL, la carga
reventaría en Postgres —lejos, tarde y con un mensaje feo—. Aquí falla antes,
en `make check`.
"""

from __future__ import annotations

import re

import polars as pl
import pytest

from loader.load import DDL_PATH, SCHEMA, TABLES, statements

# Un dtype de polars y el tipo de Postgres que le corresponde. La ingesta de ADBC
# es binaria: si el tipo declarado no encaja con el buffer de Arrow, falla.
TYPE_MAP = {
    pl.Int64: "bigint",
    pl.Int32: "integer",
    pl.Float64: "double precision",
    pl.Boolean: "boolean",
    pl.Date: "date",
    pl.Datetime: "timestamp",
    pl.String: "text",
}

CREATE_TABLE = re.compile(rf"CREATE TABLE IF NOT EXISTS {SCHEMA}\.(\w+)\s*\((.+)\)", re.DOTALL)


@pytest.fixture(scope="session")
def ddl() -> dict[str, dict[str, str]]:
    """El DDL parseado: {tabla: {columna: tipo}}, en orden de declaración."""
    parsed = {}
    for statement in statements(DDL_PATH.read_text(encoding="utf-8")):
        match = CREATE_TABLE.search(statement)
        if match is None:
            continue
        table, body = match.groups()
        columns = {}
        for line in body.split(","):
            column, *sql_type = line.split()
            columns[column] = " ".join(sql_type)
        parsed[table] = columns
    return parsed


def test_ddl_declares_the_nine_raw_tables(ddl, tables):
    assert set(ddl) == set(TABLES)
    assert set(ddl) == set(tables)


def test_columns_match_the_generator(ddl, tables):
    """Mismas columnas y en el mismo orden que el Parquet."""
    for name in TABLES:
        assert list(ddl[name]) == tables[name].columns, f"raw.{name} no cuadra con el generador"


def test_types_match_the_generator(ddl, tables):
    for name in TABLES:
        for column, dtype in tables[name].schema.items():
            expected = TYPE_MAP[dtype.base_type()]
            assert ddl[name][column] == expected, f"raw.{name}.{column} deberia ser {expected}"


def test_dirty_columns_land_as_text(ddl):
    """Las tres columnas con zonas horarias mezcladas entran sin tipar.

    Tiparlas resolvería en la ingesta el problema que staging tiene que resolver.
    Va explícito para que un refactor no lo "arregle" sin querer.
    """
    assert ddl["tickets"]["created_at"] == "text"
    assert ddl["tickets"]["resolved_at"] == "text"
    assert ddl["survey_invitations"]["fecha_envio"] == "text"
    # En contraste, esta la escribe un solo proveedor y llega limpia.
    assert ddl["survey_responses"]["fecha_respuesta"] == "timestamp"


def test_raw_has_no_constraints():
    """`raw` es landing zone, no un OLTP.

    Una constraint aquí haría fallar la carga con datos que deben entrar sucios:
    los duplicados de cliente y los centinelas del score están sembrados aposta.
    """
    # Sobre los statements, no sobre el archivo: los comentarios de cabecera
    # nombran justamente las constraints que explican por qué no están.
    executed = " ".join(statements(DDL_PATH.read_text(encoding="utf-8"))).upper()
    for constraint in ("PRIMARY KEY", "FOREIGN KEY", "REFERENCES", "NOT NULL", "CHECK", "UNIQUE"):
        assert constraint not in executed, f"raw no debe declarar {constraint}"


def test_statements_splits_and_drops_comments():
    sql = "-- comentario\nCREATE SCHEMA IF NOT EXISTS raw;\n\nSELECT 1; -- otro\n"
    assert statements(sql) == ["CREATE SCHEMA IF NOT EXISTS raw", "SELECT 1"]
