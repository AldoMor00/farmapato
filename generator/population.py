"""Catálogo de productos y padrón de clientes.

El padrón no nace completo: se arranca con `initial_customers` (altas anteriores
al periodo simulado) y cada mes entra una cohorte nueva según
`monthly_growth_rate`, hasta llegar a `active_customers_end`.

Convención interna: las fechas viven como **ordinales enteros**
(`datetime.date.toordinal`). Comparar y muestrear enteros es vectorizable y
evita arrays de objetos; la conversión a fecha ocurre una sola vez, al ensamblar
los Parquet.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from faker import Faker

# Tamaño del catálogo de nombres. Faker se usa SOLO para construirlo (una vez,
# con su propia semilla); el muestreo de los 80k clientes es vectorizado con
# NumPy sobre estos arrays. Así el realismo mexicano no cuesta un segundo RNG
# global corriendo dentro de la simulación, que rompería el determinismo.
NAME_CATALOG_SIZE = 3000

# Sentinel para "sin cancelar": un ordinal muy por delante del periodo simulado,
# así `sub_cancel > hoy` responde "sigue activa" sin ramificar por None.
NEVER = 4_000_000


@dataclass
class Products:
    product_id: np.ndarray
    category: np.ndarray  # índice dentro de cfg["catalog"]["categories"]
    price: np.ndarray
    requires_prescription: np.ndarray
    is_chronic: np.ndarray


@dataclass
class Customers:
    """Estado del padrón. Todos los arrays están alineados por índice."""

    customer_id: np.ndarray
    full_name: np.ndarray
    email: np.ndarray
    signup_ord: np.ndarray
    city: np.ndarray  # índice en cfg["geography"]["cities"]
    birth_year: np.ndarray
    acquisition_channel: np.ndarray
    preferred_channel: np.ndarray  # índice en channels.distribution
    latent_base: np.ndarray
    # Cuándo deja de comprar. Los que cancelan el Plan no desaparecen: una parte
    # sigue comprando transaccional (`post_churn_transactional_rate`).
    inactive_ord: np.ndarray

    # Plan Resurtido. `sub_condition` es -1 para quien no tiene suscripción.
    sub_condition: np.ndarray
    sub_start_ord: np.ndarray
    sub_cancel_ord: np.ndarray  # NEVER mientras siga activa
    sub_reason: np.ndarray  # índice en cancellation_reasons, -1 si activa
    sub_monthly_value: np.ndarray
    sub_bimonthly: np.ndarray

    # Memoria de eventos operativos: impacto de los últimos 3 meses, por cliente.
    impact: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))

    def __len__(self) -> int:
        return len(self.customer_id)

    @property
    def has_sub(self) -> np.ndarray:
        return self.sub_condition >= 0

    def sub_active_on(self, day_ord: int) -> np.ndarray:
        """Suscripciones vigentes en una fecha: dadas de alta y sin cancelar."""
        return self.has_sub & (self.sub_start_ord <= day_ord) & (self.sub_cancel_ord > day_ord)

    def active_on(self, day_ord: int) -> np.ndarray:
        """Clientes que ya se dieron de alta y todavía compran."""
        return (self.signup_ord <= day_ord) & (self.inactive_ord > day_ord)


def build_products(cfg: dict[str, Any], rng: np.random.Generator) -> Products:
    cats = cfg["catalog"]["categories"]
    n = cfg["catalog"]["n_products"]
    shares = np.array([c["share"] for c in cats], dtype=float)
    category = rng.choice(len(cats), size=n, p=shares / shares.sum())

    means = np.array([c["price_mean"] for c in cats], dtype=float)[category]
    sds = np.array([c["price_sd"] for c in cats], dtype=float)[category]
    # Precio lognormal: sin colas negativas y con la asimetría a la derecha que
    # tiene cualquier catálogo real (muchos baratos, pocos caros).
    log_sigma = np.sqrt(np.log1p((sds / means) ** 2))
    log_mu = np.log(means) - 0.5 * log_sigma**2
    price = np.round(rng.lognormal(log_mu, log_sigma), 2)

    return Products(
        product_id=np.arange(1, n + 1),
        category=category,
        price=price,
        requires_prescription=np.array([c["requires_prescription"] for c in cats])[category],
        is_chronic=np.array([c["name"].startswith("cronicos") for c in cats])[category],
    )


def build_name_catalog(seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Nombres y apellidos mexicanos, extraídos de faker una sola vez."""
    fake = Faker("es_MX")
    Faker.seed(seed)
    firsts = {fake.first_name() for _ in range(NAME_CATALOG_SIZE)}
    lasts = {fake.last_name() for _ in range(NAME_CATALOG_SIZE)}
    return np.array(sorted(firsts)), np.array(sorted(lasts))


def _slug(values: np.ndarray) -> np.ndarray:
    """Sin acentos, en minúsculas y sin espacios: base para el email."""
    return np.array(
        [
            unicodedata.normalize("NFKD", v)
            .encode("ascii", "ignore")
            .decode()
            .lower()
            .replace(" ", "")
            for v in values
        ]
    )


def new_cohort(
    cfg: dict[str, Any],
    rng: np.random.Generator,
    names: tuple[np.ndarray, np.ndarray],
    n: int,
    first_id: int,
    signup_ord: np.ndarray,
) -> Customers:
    """Crea `n` clientes con su satisfacción latente base y, al 30%, suscripción."""
    firsts, lasts = names
    given = rng.choice(firsts, size=n)
    paternal = rng.choice(lasts, size=n)
    maternal = rng.choice(lasts, size=n)
    full_name = np.char.add(given + " ", np.char.add(paternal + " ", maternal))

    customer_id = np.arange(first_id, first_id + n)
    # El sufijo con el id garantiza unicidad: los únicos duplicados del dataset
    # son los que `dirt.py` siembra a propósito.
    email = np.char.add(
        np.char.add(_slug(given) + ".", _slug(paternal)),
        np.char.add(customer_id.astype(str), "@example.mx"),
    )

    cities = cfg["geography"]["cities"]
    city_w = np.array([c["weight"] for c in cities], dtype=float)
    city = rng.choice(len(cities), size=n, p=city_w / city_w.sum())

    chan = cfg["channels"]["distribution"]
    preferred = rng.choice(len(chan), size=n, p=np.array(list(chan.values())))

    acq = cfg["channels"]["acquisition"]
    acquisition = rng.choice(list(acq), size=n, p=np.array(list(acq.values())))

    birth_year = np.clip(np.round(rng.normal(1978, 15, size=n)), 1935, 2007).astype(np.int32)

    # ¿Quién entra al Plan Resurtido? Se decide al alta.
    subs = cfg["subscriptions"]
    has_sub = rng.random(n) < subs["share_of_customers"]

    cond = subs["conditions"]
    sub_condition = np.where(
        has_sub, rng.choice(len(cond), size=n, p=np.array(list(cond.values()))), -1
    )
    mv = subs["monthly_value"]
    sub_monthly_value = np.where(
        has_sub,
        np.maximum(rng.normal(mv["mean"], mv["sd"], size=n), mv["min"]).round(2),
        np.nan,
    )

    # Latente base: segmento + canal + heterogeneidad individual.
    ls = cfg["latent_satisfaction"]
    base = np.where(has_sub, ls["base_mean"]["subscription"], ls["base_mean"]["transactional"])
    offsets = np.array([ls["channel_offset"][c] for c in chan])
    latent_base = base + offsets[preferred] + rng.normal(0, ls["individual_sd"], size=n)

    return Customers(
        customer_id=customer_id,
        full_name=full_name,
        email=email,
        signup_ord=signup_ord.astype(np.int64),
        city=city,
        birth_year=birth_year,
        acquisition_channel=acquisition,
        preferred_channel=preferred,
        latent_base=latent_base,
        inactive_ord=np.full(n, NEVER, dtype=np.int64),
        sub_condition=sub_condition,
        sub_start_ord=np.where(has_sub, signup_ord, NEVER).astype(np.int64),
        sub_cancel_ord=np.full(n, NEVER, dtype=np.int64),
        sub_reason=np.full(n, -1, dtype=np.int32),
        sub_monthly_value=sub_monthly_value,
        sub_bimonthly=has_sub & (rng.random(n) < subs["frequency"]["bimestral"]),
        impact=np.zeros((n, 3)),
    )


def concat_customers(a: Customers, b: Customers) -> Customers:
    """Añade la cohorte del mes al padrón."""
    if len(a) == 0:
        return b
    return Customers(
        **{f: np.concatenate([getattr(a, f), getattr(b, f)]) for f in a.__dataclass_fields__}
    )
