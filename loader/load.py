"""Carga del Parquet de la landing zone al esquema `raw` de Postgres.

Esta es la **ingesta** del pipeline: dbt transforma dentro del warehouse, quien
ingiere es este paso. Su regla única es **no limpiar nada**. El Parquet entra tal
como salió del generador —con duplicados, centinelas fuera de rango y timestamps
sin tipar— porque resolverlo es trabajo de los modelos de staging.

Postgres es estado derivado: la carga trunca y vuelve a escribir, así que correr
`make load` dos veces deja exactamente el mismo resultado.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

import polars as pl
from adbc_driver_manager.dbapi import Connection

# Las 9 tablas raw. La lista se repite aquí en vez de importarse del generador a
# propósito: los componentes se integran por la base de datos, no por imports.
# `tests/test_ddl.py` comprueba que esta copia, el DDL y el generador siguen de
# acuerdo, que es la garantía que de verdad importa.
TABLES = (
    "customers",
    "products",
    "subscriptions",
    "orders",
    "order_items",
    "deliveries",
    "tickets",
    "survey_invitations",
    "survey_responses",
)

SCHEMA = "raw"
DDL_PATH = Path(__file__).resolve().parents[1] / "sql" / "00_schema_raw.sql"

REQUIRED_ENV = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")


def connection_uri() -> str:
    """Cadena de conexión desde el entorno. El Makefile exporta el `.env`."""
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            f"Faltan variables de entorno: {', '.join(missing)}.\n"
            "Copia .env.example a .env (local) o expórtalas en el workflow (CI)."
        )
    # quote(): una contraseña con '@' o '/' partiría la URI en silencio.
    user = quote(os.environ["POSTGRES_USER"], safe="")
    password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5433")
    return f"postgresql://{user}:{password}@{host}:{port}/{os.environ['POSTGRES_DB']}"


def statements(sql: str) -> list[str]:
    """Parte un script SQL en statements sueltos.

    ADBC habla el protocolo extendido de Postgres, que rechaza varios comandos en
    una misma llamada ("cannot insert multiple commands into a prepared
    statement"). Cortar por `;` vale mientras el script no tenga punto y coma
    dentro de un literal; el DDL es nuestro y no lo tiene.
    """
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def apply_schema(conn: Connection) -> None:
    """Aplica `sql/00_schema_raw.sql`, que es idempotente (IF NOT EXISTS).

    Se corre en cada carga a propósito: el script montado en initdb sólo se
    ejecuta cuando el volumen se crea de cero, así que si fuera el único camino,
    tocar el DDL exigiría acordarse de `make db-reset`.
    """
    with conn.cursor() as cur:
        for statement in statements(DDL_PATH.read_text(encoding="utf-8")):
            cur.execute(statement)


def truncate(conn: Connection, tables: tuple[str, ...] = TABLES) -> None:
    """Vacía las 9 tablas de un golpe: es lo que hace la carga repetible."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(f"{SCHEMA}.{table}" for table in tables))


def ingest(conn: Connection, name: str, df: pl.DataFrame) -> int:
    """Empuja el DataFrame a `raw.<name>` sin pasar por texto.

    `adbc_ingest` manda los buffers de Arrow directamente al protocolo binario de
    Postgres, y el DataFrame de polars viaja por la interfaz PyCapsule sin copia
    intermedia. No se usa `df.write_database` —que envuelve esta misma llamada—
    porque hace `commit()` por tabla, y aquí la carga entera es una transacción.
    """
    with conn.cursor() as cur:
        return cur.adbc_ingest(name, df, mode="append", db_schema_name=SCHEMA)


def load(conn: Connection, src: str | Path, tables: tuple[str, ...] = TABLES) -> dict[str, int]:
    """Deja `raw` con exactamente el contenido del Parquet de `src`.

    `src` es un directorio local o un URI `abfss://` de la landing zone. La ruta
    se une con f-string porque `Path` no sobrevive a un URI, y la credencial de
    Azure la resuelve polars sola (`credential_provider="auto"`).
    """
    apply_schema(conn)
    truncate(conn, tables)
    return {name: ingest(conn, name, pl.read_parquet(f"{src}/{name}.parquet")) for name in tables}
