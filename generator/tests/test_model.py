"""Unitarios del modelo generativo. Rápidos: no generan el dataset."""

from __future__ import annotations

import numpy as np
import pytest

from generator import satisfaction, surveys
from generator.churn import cancellations


def test_memory_weights_decay_by_halflife(cfg):
    """Cada casilla de memoria pesa la mitad que la de 30 días antes."""
    halflife = cfg["latent_satisfaction"]["event_decay_halflife_days"]
    w = satisfaction.MEMORY_WEIGHTS
    assert w[0] > w[1] > w[2] > 0
    np.testing.assert_allclose(w[1] / w[0], 0.5 ** (30 / halflife), rtol=1e-9)
    np.testing.assert_allclose(w[2] / w[1], 0.5 ** (30 / halflife), rtol=1e-9)


def test_memory_window_matches_config():
    """Tres casillas mensuales cubren la ventana de 90 días del config."""
    assert len(satisfaction.MEMORY_WEIGHTS) * 30 == 90


def test_delivery_effect_is_flat_before_threshold_and_saturates(cfg):
    """La no-linealidad sembrada: medio día no se nota, cinco días satura."""
    dd = cfg["operational_effects"]["delivery_delay"]
    effect = satisfaction._delivery_effect(cfg, np.array([0.0, 0.5, 2.0, 5.0, 10.0]))

    assert abs(effect[1]) < abs(effect[2]) < abs(effect[3])
    # En el umbral, exactamente la mitad del daño máximo.
    np.testing.assert_allclose(effect[2], dd["max_effect"] / 2, rtol=1e-9)
    # Y no crece sin límite.
    assert abs(effect[4]) <= abs(dd["max_effect"])


def test_response_bias_preserves_the_base_rate(cfg):
    """El sesgo cambia QUIÉN responde, no cuántos.

    Es la razón de ser de `normalize_to_base_rate`: sin normalizar, la curva en
    U y el multiplicador de canal inflarían el 8% del relacional a ~11% y el
    config estaría mintiendo sobre su propio número.
    """
    rng = np.random.default_rng(0)
    n = 200_000
    latent = rng.normal(0.4, 1.0, size=n)
    channel = rng.integers(0, 4, size=n)

    answered = surveys.respond_mask(cfg, rng, "nps_relacional", latent, channel)
    base = cfg["surveys"]["touchpoints"]["nps_relacional"]["base_response_rate"]
    assert answered.mean() == pytest.approx(base, abs=0.005)


def test_response_bias_favours_the_extremes(cfg):
    """Los satisfechos y los enojados responden más que los indiferentes."""
    rng = np.random.default_rng(0)
    n = 300_000
    latent = rng.normal(0.4, 1.0, size=n)
    channel = np.zeros(n, dtype=int)

    answered = surveys.respond_mask(cfg, rng, "nps_relacional", latent, channel)
    middle = np.abs(latent - latent.mean()) < 0.25
    assert answered[~middle].mean() > answered[middle].mean()


@pytest.mark.parametrize(("scale", "lo", "hi"), [("nps", 0, 10), ("csat", 1, 5), ("ces", 1, 7)])
def test_scores_stay_inside_their_scale(cfg, scale, lo, hi):
    rng = np.random.default_rng(0)
    latent = rng.normal(0.4, 1.5, size=50_000)
    score = surveys.score_from_latent(cfg, scale, latent)
    assert score.min() >= lo and score.max() <= hi


def test_nps_mix_matches_the_designed_distribution(cfg):
    """Los cutpoints producen el pico en 9-10 y ~20% de detractores."""
    rng = np.random.default_rng(0)
    latent = rng.normal(0.45, 1.0, size=300_000)
    score = surveys.score_from_latent(cfg, "nps", latent)

    promoters = (score >= 9).mean()
    detractors = (score <= 6).mean()
    assert 0.40 < promoters < 0.55
    assert 0.15 < detractors < 0.28


def test_churn_rises_as_satisfaction_falls(cfg):
    """El signo del coeficiente: menos satisfacción, más cancelación."""
    rng = np.random.default_rng(0)
    n = 300_000
    happy, _ = cancellations(cfg, rng, np.full(n, 1.5))
    unhappy, _ = cancellations(cfg, rng, np.full(n, -1.5))
    assert unhappy.mean() > 3 * happy.mean()


def test_independent_churn_share_matches_target(cfg):
    """Parte del churn no se explica con satisfacción, y eso es deliberado.

    Sostiene el pseudo-R² del modelo logístico en el rango realista de
    0.05-0.10 y es lo que el informe discutirá en las limitaciones.
    """
    rng = np.random.default_rng(0)
    latent = rng.normal(0.55, 1.0, size=400_000)
    cancels, reason = cancellations(cfg, rng, latent)

    independent = (reason[cancels] != 0).mean()
    assert independent == pytest.approx(cfg["churn"]["independent_share_target"], abs=0.10)
