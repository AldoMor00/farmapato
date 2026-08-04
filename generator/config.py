"""Carga de `config.yaml` y derivación de semillas.

El generador no contiene números mágicos: todo parámetro sale de este archivo.
Las sub-semillas se derivan de `meta.seed` con `numpy.random.SeedSequence`, así
que cada componente tiene su propio generador independiente y añadir uno nuevo
no desplaza los números de los demás.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"

# La memoria de eventos avanza en casillas de un mes porque el loop de la
# simulación es mensual. Es la resolución del modelo, no un parámetro suyo: por
# eso vive aquí y no en el YAML.
MEMORY_SLOT_DAYS = 30


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Lee el YAML de parámetros del modelo generativo."""
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def month_starts(cfg: dict[str, Any]) -> list[dt.date]:
    """Primer día de cada mes simulado, de `start_date` a `end_date`."""
    start, end = cfg["meta"]["start_date"], cfg["meta"]["end_date"]
    months = []
    year, month = start.year, start.month
    while dt.date(year, month, 1) <= end:
        months.append(dt.date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def memory_weights(cfg: dict[str, Any]) -> np.ndarray:
    """Peso de cada casilla mensual de la memoria de eventos operativos.

    El impacto de un evento decae con vida media `event_decay_halflife_days` y
    se olvida del todo a los `event_memory_days`. Como el simulador avanza mes a
    mes, la memoria son casillas de 30 días y el decay se evalúa en el centro de
    cada una: con la ventana de 90 días salen tres, a los 15, 45 y 75.
    """
    ls = cfg["latent_satisfaction"]
    centers = np.arange(MEMORY_SLOT_DAYS / 2, ls["event_memory_days"], MEMORY_SLOT_DAYS)
    return 0.5 ** (centers / ls["event_decay_halflife_days"])


def days_in_month(first_day: dt.date) -> int:
    nxt = (
        dt.date(first_day.year + 1, 1, 1)
        if first_day.month == 12
        else dt.date(first_day.year, first_day.month + 1, 1)
    )
    return (nxt - first_day).days


class Rngs:
    """Generadores nombrados, todos derivados de la semilla maestra.

    `SeedSequence.spawn` no sirve aquí: el orden de los spawns determina el
    resultado, así que añadir un componente cambiaría los datos de los demás.
    Derivar por nombre (hash estable del string) mantiene cada flujo aislado.
    """

    def __init__(self, master_seed: int) -> None:
        self._master = master_seed
        self._cache: dict[str, np.random.Generator] = {}

    def get(self, name: str) -> np.random.Generator:
        if name not in self._cache:
            entropy = [self._master, *(ord(c) for c in name)]
            self._cache[name] = np.random.default_rng(np.random.SeedSequence(entropy))
        return self._cache[name]
