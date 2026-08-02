"""Fixtures compartidas.

El dataset completo se genera **una sola vez por sesión** (~6 s) y se reparte
entre todos los tests que lo necesitan. Generarlo por test multiplicaría el
tiempo sin añadir cobertura: la simulación es determinista.
"""

from __future__ import annotations

import pytest

from generator.cli import generate
from generator.config import load_config


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def tables():
    """Las 9 tablas raw a escala completa, tal como se escriben a Parquet."""
    return generate()
