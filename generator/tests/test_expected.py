"""El bloque `expected` del config, asertado sobre el dataset generado.

Es el test que da sentido a la frase "el modelo generativo está calibrado, no es
un accidente": si alguien toca un peso del config o la lógica de la simulación y
el hallazgo central se desdibuja, esto lo atrapa.
"""

from __future__ import annotations

import pytest

from .metrics import CALCULATORS


@pytest.mark.parametrize("metric", list(CALCULATORS))
def test_expected_metric_in_range(metric, tables, cfg):
    bounds = cfg["expected"][metric]
    value = float(CALCULATORS[metric](tables, cfg))
    assert bounds["min"] <= value <= bounds["max"], (
        f"{metric} = {value:.4f}, fuera de [{bounds['min']}, {bounds['max']}]"
    )


def test_every_expected_entry_has_a_calculator(cfg):
    """Nadie puede añadir una expectativa al config y dejarla sin comprobar."""
    assert set(cfg["expected"]) == set(CALCULATORS)
