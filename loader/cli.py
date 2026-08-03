"""Punto de entrada: `python -m loader --src data/raw`.

Lee el Parquet que dejó el generador y reemplaza con él el contenido de `raw`.
`--src` acepta un directorio local o el URI `abfss://` de la landing zone en ADLS
Gen2, y el resto del paso de carga es idéntico en los dos casos: por eso local y
CI ingieren exactamente el mismo dato crudo.
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
    # str y no Path: un URI abfss:// no sobrevive a Path (ver generator/cli.py).
    parser.add_argument("--src", default="data/raw")
    args = parser.parse_args()
    src = args.src.rstrip("/")

    # El aviso amable sólo aplica en local; un URI de nube no se puede statear.
    if "://" not in src and not Path(src).is_dir():
        raise SystemExit(f"No existe {src}. Corre `make generate` primero.")

    started = time.perf_counter()
    with dbapi.connect(connection_uri()) as conn:
        counts = load(conn, src)
        # Un único commit al final. Si una tabla falla a mitad, la base se queda
        # con la carga anterior entera en vez de con media carga nueva.
        conn.commit()

    for name, rows in counts.items():
        print(f"{name:20} {rows:>9,} filas")
    print(f"\n{len(counts)} tablas en raw ({time.perf_counter() - started:.1f}s)")


if __name__ == "__main__":
    main()
