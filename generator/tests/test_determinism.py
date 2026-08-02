"""Reproducibilidad: la misma semilla da exactamente el mismo dataset.

Es lo que sostiene la promesa de `make all`: el CI y la máquina local tienen que
poder reconstruir el mismo warehouse bit a bit.
"""

from __future__ import annotations

import polars as pl

from generator.cli import generate
from generator.config import Rngs


def test_same_seed_gives_the_same_data(tables):
    again = generate()
    for name, df in tables.items():
        assert df.equals(again[name]), f"{name} cambió entre corridas"


def test_a_different_seed_gives_different_data(cfg, tmp_path):
    import yaml

    other = dict(cfg)
    other["meta"] = dict(cfg["meta"], seed=cfg["meta"]["seed"] + 1)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(other), encoding="utf-8")

    changed = generate(path)
    assert not changed["orders"].equals(pl.DataFrame())
    assert changed["survey_responses"]["score"].sum() != 0


def test_named_streams_are_independent():
    """Añadir un componente no debe desplazar los números de los demás.

    Por eso las sub-semillas se derivan del nombre y no de `SeedSequence.spawn`,
    donde el orden de creación decide el resultado.
    """
    a = Rngs(123)
    b = Rngs(123)
    first = a.get("orders").random(5)
    b.get("surveys").random(5)  # otro componente pide números antes
    second = b.get("orders").random(5)
    assert (first == second).all()
