"""Punto de entrada: `python -m generator --out data/raw`.

Escribe las 9 tablas raw en Parquet. Ese Parquet es la única capa durable del
pipeline —vive en ADLS Gen2— y de ahí lo lee tanto la máquina local como el CI,
para que ambos carguen exactamente el mismo dato crudo.

`--out` acepta un directorio local o un URI `abfss://`; polars resuelve la
autenticación de Azure por su cuenta (ver `main`).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import polars as pl

from . import dirt, tables
from .config import Rngs, load_config
from .simulate import run, stack

TABLE_ORDER = [
    "customers",
    "products",
    "subscriptions",
    "orders",
    "order_items",
    "deliveries",
    "tickets",
    "survey_invitations",
    "survey_responses",
]


def generate(config_path: Path | None = None) -> dict[str, pl.DataFrame]:
    """Corre la simulación completa y devuelve las 9 tablas, ya ensuciadas."""
    cfg = load_config(config_path)
    rngs = Rngs(cfg["meta"]["seed"])

    acc, cust, prods = run(cfg)
    built = tables.build_tables(cfg, acc, cust, prods, rngs.get("tables"))

    aux = stack(acc.responses)
    chan_names = np.array(list(cfg["channels"]["distribution"]))
    return dirt.apply_all(built, aux, cfg, rngs.get("dirt"), chan_names)


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera los datos sintéticos de FarmaPato.")
    # `--out` es str y no Path a propósito: Path("abfss://a@b/c") colapsa la doble
    # barra del esquema y en Windows cambia los separadores. Se une con f-string.
    parser.add_argument("--out", default="data/raw")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    out = args.out.rstrip("/")

    started = time.perf_counter()
    result = generate(args.config)
    for name in TABLE_ORDER:
        df = result[name]
        # mkdir crea el directorio local si falta; contra ADLS no hace nada.
        # La credencial la resuelve polars con credential_provider="auto", que
        # por debajo es DefaultAzureCredential: `az login` en local, OIDC en CI.
        df.write_parquet(f"{out}/{name}.parquet", mkdir=True)
        print(f"{name:20} {len(df):>9,} filas")
    print(f"\n{len(TABLE_ORDER)} tablas en {out} ({time.perf_counter() - started:.1f}s)")


if __name__ == "__main__":
    main()
