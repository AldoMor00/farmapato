"""Invitaciones a encuesta y respuestas.

Las invitaciones se generan siempre; las respuestas dependen de la latente y del
canal, que es de donde sale el sesgo de no respuesta. Separar ambas tablas es
deliberado: habilita medir tasas de respuesta reales y analizar ese sesgo.
"""

from __future__ import annotations

from typing import Any

import numpy as np

TOUCHPOINTS = [
    "nps_relacional",
    "nps_transaccional",
    "csat_ticket",
    "ces_resurtido",
    "ces_facturacion",
]


def respond_mask(
    cfg: dict[str, Any],
    rng: np.random.Generator,
    touchpoint: str,
    latent: np.ndarray,
    channel: np.ndarray,
) -> np.ndarray:
    """Quién contesta.

    El multiplicador combina extremidad (responden más los que tienen algo que
    decir, en U) y canal. Se **normaliza** dividiendo por su media, de modo que
    la tasa realizada sea la `base_response_rate` del touchpoint: el sesgo
    cambia QUIÉN responde, no cuántos. Sin normalizar, el 8% del relacional se
    inflaría a ~11% y el config estaría mintiendo sobre su propio número.
    """
    bias = cfg["surveys"]["response_bias"]
    base = cfg["surveys"]["touchpoints"][touchpoint]["base_response_rate"]
    if len(latent) == 0:
        return np.zeros(0, dtype=bool)

    extremity = 1 + bias["extremity_weight"] * np.abs(latent - latent.mean())
    extremity = np.minimum(extremity, bias["max_multiplier"])

    chan_names = list(cfg["channels"]["distribution"])
    chan_mult = np.array([bias["channel_multiplier"][c] for c in chan_names])
    mult = extremity * chan_mult[channel]

    if bias["normalize_to_base_rate"]:
        mult = mult / mult.mean()
    return rng.random(len(latent)) < np.clip(base * mult, 0, 1)


def score_from_latent(cfg: dict[str, Any], scale: str, latent: np.ndarray) -> np.ndarray:
    """Probit ordenado: la latente cae entre cortes y sale un punto de escala.

    NPS queda en 0-10; CSAT en 1-5; CES en 1-7 (7 = muy fácil).
    """
    cutpoints = np.array(cfg["surveys"]["scales"][scale]["cutpoints"])
    raw = np.searchsorted(cutpoints, latent)
    return raw.astype(np.int16) if scale == "nps" else (raw + 1).astype(np.int16)


def response_lag_days(cfg: dict[str, Any], rng: np.random.Generator, n: int) -> np.ndarray:
    """Cuánto tarda en contestar quien contesta."""
    lag = cfg["surveys"]["response_bias"]["response_lag_days"]
    return np.ceil(rng.gamma(lag["shape"], lag["scale"], size=n)).astype(np.int64)


def verbatim_mask(
    cfg: dict[str, Any], rng: np.random.Generator, score: np.ndarray, scale: str
) -> np.ndarray:
    """Quién además escribe un comentario. Los detractores escriben más."""
    vb = cfg["surveys"]["verbatim"]
    p = np.full(len(score), vb["base_rate"])
    if scale == "nps":
        detractor = score <= cfg["surveys"]["scales"]["nps"]["detractor_max"]
        p = np.where(detractor, p * vb["detractor_multiplier"], p)
    return rng.random(len(score)) < np.clip(p, 0, 1)
