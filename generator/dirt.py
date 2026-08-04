"""Suciedad sembrada a propósito.

Cada elemento existe para que un modelo de staging tenga que resolverlo y un test
de dbt lo atrape. Está documentada aquí y en `config.yaml`, pero el repo la trata
como si se hubiera "descubierto" al perfilar los datos — que es como llega en la
vida real.

Se aplica al final, sobre las tablas ya ensambladas: la simulación produce datos
limpios y esto los ensucia, igual que un sistema fuente ensucia lo que un proceso
correcto generó.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

CALL_CENTER = "call_center"


def _utc_offset(cfg: dict[str, Any]) -> tuple[np.timedelta64, str]:
    """Offset de `meta.timezone`: como delta hacia UTC y como etiqueta de texto.

    Se evalúa una sola vez, en `start_date`. México eliminó el horario de verano
    en 2022, así que en la ventana simulada el offset es constante; una zona que
    sí lo aplicara obligaría a resolverlo timestamp a timestamp.
    """
    tz = ZoneInfo(cfg["meta"]["timezone"])
    midnight = dt.datetime.combine(cfg["meta"]["start_date"], dt.time())
    seconds = int(tz.utcoffset(midnight).total_seconds())
    hours, minutes = divmod(abs(seconds) // 60, 60)
    sign = "-" if seconds < 0 else "+"
    return np.timedelta64(-seconds, "s"), f"{sign}{hours:02d}:{minutes:02d}"


def _add_accents(names: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Reintroduce acentos donde el otro sistema los perdió."""
    swaps = str.maketrans("aeiou", "áéíóú")
    out = []
    for name in names:
        chars = list(name)
        vowels = [i for i, c in enumerate(chars) if c.lower() in "aeiou"]
        if vowels:
            i = int(rng.choice(vowels))
            chars[i] = chars[i].translate(swaps)
        out.append("".join(chars))
    return np.array(out)


def _strip_accents(values: np.ndarray) -> np.ndarray:
    return np.array(
        [unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode() for v in values]
    )


def duplicate_customers(
    customers: pl.DataFrame, cfg: dict[str, Any], rng: np.random.Generator
) -> pl.DataFrame:
    """Reingresa a ~1.5% de los clientes con variaciones que rompen el match exacto.

    El duplicado lleva un customer_id nuevo, así que las tablas de hechos siguen
    siendo consistentes; lo que hay que resolver en staging es que dos ids son la
    misma persona. La clave util es el email normalizado.
    """
    dc = cfg["dirt"]["duplicate_customers"]
    n = len(customers)
    idx = rng.choice(n, size=int(n * dc["rate"]), replace=False)
    dup = customers[idx]

    # polars devuelve las columnas de texto como object; las operaciones
    # vectorizadas de numpy sobre strings necesitan dtype <U.
    name = dup["nombre_completo"].to_numpy().astype(str)
    email = dup["email"].to_numpy().astype(str)
    variation = rng.integers(0, len(dc["variations"]), size=len(idx))

    name = np.where(variation == 0, _add_accents(_strip_accents(name), rng), name)
    name = np.where(variation == 1, np.char.upper(name), name)
    name = np.where(variation == 2, np.char.add("  ", np.char.add(name, " ")), name)

    local = np.array([e.split("@")[0] for e in email])
    domain = np.array([e.split("@")[1] for e in email])
    # Alias de correo: el punto y el "+" no cambian el buzón, pero sí el string.
    pairs = list(zip(local, domain, strict=True))
    dotted = np.array([f"{loc[:3]}.{loc[3:]}@{dom}" for loc, dom in pairs])
    plussed = np.array([f"{loc}+farmapato@{dom}" for loc, dom in pairs])
    email = np.where(variation == 3, dotted, email)
    email = np.where(variation == 4, plussed, email)

    max_id = int(customers["customer_id"].max())
    dup = dup.with_columns(
        customer_id=pl.Series(np.arange(max_id + 1, max_id + 1 + len(idx))),
        nombre_completo=pl.Series(name),
        email=pl.Series(email),
    )
    return pl.concat([customers, dup])


def call_center_scale_mismatch(
    responses: pl.DataFrame,
    aux: dict[str, np.ndarray],
    cfg: dict[str, Any],
    chan_names: np.ndarray,
) -> pl.DataFrame:
    """El CSAT del call center viene en 1-10, no en 1-5: otro proveedor.

    Es la trampa más jugosa del dataset: sin corregirla infla el promedio global,
    y el error pasa desapercibido porque 1-10 es una escala perfectamente
    plausible para CSAT.
    """
    mismatch = cfg["dirt"]["call_center_scale_mismatch"]
    affected = (aux["touchpoint"] == mismatch["applies_to"]) & (
        chan_names[aux["customer_channel"]] == mismatch["channel"]
    )
    lo, hi = mismatch["native_scale"]
    # 1-5 → 1-10 con el mapeo lineal que usaría el proveedor.
    rescaled = np.round(lo + (responses["score"].to_numpy() - 1) * (hi - lo) / 4).astype(np.int64)
    return responses.with_columns(
        score=pl.Series(np.where(affected, rescaled, responses["score"].to_numpy()))
    )


def test_accounts(
    customers: pl.DataFrame, cfg: dict[str, Any], rng: np.random.Generator
) -> pl.DataFrame:
    """Cuentas internas de QA que nadie limpió del padrón de producción."""
    ta = cfg["dirt"]["test_accounts"]
    n = len(customers)
    idx = rng.choice(n, size=int(n * ta["rate"]), replace=False)
    email = customers["email"].to_numpy().astype(str).copy()
    local = np.array([email[i].split("@")[0] for i in idx])
    pattern = rng.integers(0, 3, size=len(idx))
    email[idx] = np.where(
        pattern == 0,
        np.char.add(local, "@farmapato.test"),
        np.where(
            pattern == 1,
            np.char.add(np.char.add("qa+", local), "@farmapato.com"),
            np.char.add(np.char.add("prueba_", local), "@example.mx"),
        ),
    )
    return customers.with_columns(email=pl.Series(email))


def out_of_range_scores(
    responses: pl.DataFrame, cfg: dict[str, Any], rng: np.random.Generator
) -> pl.DataFrame:
    """Valores centinela que algún sistema escribió en el campo del score."""
    oor = cfg["dirt"]["out_of_range_scores"]
    n = len(responses)
    idx = rng.choice(n, size=int(n * oor["rate"]), replace=False)
    score = responses["score"].to_numpy().astype(np.int64).copy()
    score[idx] = rng.choice(oor["values"], size=len(idx))
    return responses.with_columns(score=pl.Series(score))


def mixed_timezones(
    df: pl.DataFrame, columns: list[str], cfg: dict[str, Any], rng: np.random.Generator
) -> pl.DataFrame:
    """Tres sistemas fuente escribiendo la misma hora de tres maneras.

    Uno exporta en UTC con sufijo Z, otro en hora local con offset explícito, y
    otro sin marca de zona ninguna. La columna sale como **texto**, que es como
    llega de verdad cuando la fuente es un CSV o un JSON: si saliera tipada, el
    problema estaría resuelto antes de empezar y staging no tendría nada que
    hacer. Interpretar el naive como hora local de México es la decisión que hay
    que tomar (y documentar) aguas abajo.
    """
    mt = cfg["dirt"]["mixed_timezones"]
    offset, label = _utc_offset(cfg)
    out = df
    for col in columns:
        local = df[col].to_numpy().astype("datetime64[s]")
        which = rng.random(len(local))
        as_utc = local + offset

        utc = which < mt["utc_share"]
        naive = which >= 1 - mt["naive_share"]
        text = np.where(
            utc,
            np.char.add(as_utc.astype(str), "Z"),
            np.where(naive, local.astype(str), np.char.add(local.astype(str), label)),
        )
        out = out.with_columns(pl.Series(col, text))
    return out


def inject_nulls(
    df: pl.DataFrame, column: str, rate: float, rng: np.random.Generator
) -> pl.DataFrame:
    idx = np.flatnonzero(rng.random(len(df)) < rate)
    return df.with_columns(df[column].scatter(idx, None))


def apply_all(
    tables: dict[str, pl.DataFrame],
    aux: dict[str, np.ndarray],
    cfg: dict[str, Any],
    rng: np.random.Generator,
    chan_names: np.ndarray,
) -> dict[str, pl.DataFrame]:
    t = dict(tables)
    nulls = cfg["dirt"]["nulls"]

    t["survey_responses"] = call_center_scale_mismatch(t["survey_responses"], aux, cfg, chan_names)
    t["survey_responses"] = out_of_range_scores(t["survey_responses"], cfg, rng)
    t["customers"] = duplicate_customers(t["customers"], cfg, rng)
    t["customers"] = test_accounts(t["customers"], cfg, rng)
    t["customers"] = inject_nulls(t["customers"], "anio_nacimiento", nulls["birth_year"], rng)
    t["customers"] = inject_nulls(
        t["customers"], "canal_adquisicion", nulls["acquisition_channel"], rng
    )
    t["tickets"] = mixed_timezones(t["tickets"], ["created_at", "resolved_at"], cfg, rng)
    t["survey_invitations"] = mixed_timezones(t["survey_invitations"], ["fecha_envio"], cfg, rng)
    return t
