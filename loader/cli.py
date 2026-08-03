"""Punto de entrada: `python -m loader --src data/raw`.

Lee el Parquet que dejó el generador y reemplaza con él el contenido de `raw`.
En producción ese Parquet se descarga antes desde ADLS Gen2; el paso de carga no
distingue de dónde salió el directorio, y por eso local y CI cargan el mismo dato.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from adbc_driver_postgresql import dbapi

from .load import connection_uri, load


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Carga el Parquet de la landing zone al esquema raw de Postgres."
    )
    parser.add_argument("--src", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    if not args.src.is_dir():
        raise SystemExit(f"No existe {args.src}. Corre `make generate` primero.")

    started = time.perf_counter()
    with dbapi.connect(connection_uri()) as conn:
        counts = load(conn, args.src)
        # Un único commit al final. Si una tabla falla a mitad, la base se queda
        # con la carga anterior entera en vez de con media carga nueva.
        conn.commit()

    for name, rows in counts.items():
        print(f"{name:20} {rows:>9,} filas")
    print(f"\n{len(counts)} tablas en raw ({time.perf_counter() - started:.1f}s)")


if __name__ == "__main__":
    main()
