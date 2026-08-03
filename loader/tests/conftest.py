"""Fixtures del paso de carga.

La fixture `tables` se repite respecto a `generator/tests/conftest.py` en vez de
compartirse desde un conftest en la raíz: cuesta una generación extra (~6 s) y
mantiene los dos componentes independientes, que es la propiedad que importa.
"""

from __future__ import annotations

import pytest

from generator.cli import generate


@pytest.fixture(scope="session")
def tables():
    """Las 9 tablas raw tal como se escriben a Parquet."""
    return generate()
