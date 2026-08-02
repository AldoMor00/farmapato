"""Cancelación del Plan Resurtido.

El riesgo tiene dos componentes que se evalúan por separado a propósito:

1. **Ligado a la satisfacción**: una logística sobre la misma latente que
   alimenta las encuestas. De aquí sale que los detractores cancelen 3-4x más
   sin que nadie lo haya pintado.
2. **Independiente**: mudanza, alta médica, cambio de tratamiento. Es la parte
   NO explicable por satisfacción y mantiene el pseudo-R² del modelo logístico
   en el rango realista de 0.05-0.10. Hay señal, pero el churn no se "explica"
   con la encuesta — eso se discute en las limitaciones del informe.

Guardar cuál de los dos disparó cada cancelación permite validar contra
`independent_share_target` sin tener que inferirlo.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Índice de `insatisfaccion_servicio` en subscriptions.cancellation_reasons: es
# el único motivo ligado a la satisfacción, el resto es el ruido independiente.
REASON_DISSATISFACTION = 0


def _to_monthly(p90: np.ndarray | float) -> np.ndarray | float:
    """Convierte una probabilidad a 90 días en su hazard mensual equivalente."""
    return 1 - (1 - p90) ** (1 / 3)


def cancellations(
    cfg: dict[str, Any], rng: np.random.Generator, latent: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """¿Quién cancela este mes y por qué?

    Devuelve una máscara de cancelación y el índice del motivo.
    """
    ch = cfg["churn"]
    log = ch["logistic"]

    p90_sat = 1 / (1 + np.exp(-(log["intercept"] + log["latent_coefficient"] * latent)))
    by_dissatisfaction = rng.random(len(latent)) < _to_monthly(p90_sat)
    by_independent = rng.random(len(latent)) < _to_monthly(ch["independent_hazard_90d"])

    cancels = by_dissatisfaction | by_independent
    other_reasons = np.arange(1, len(cfg["subscriptions"]["cancellation_reasons"]))
    reason = np.where(
        by_dissatisfaction,
        REASON_DISSATISFACTION,
        rng.choice(other_reasons, size=len(latent)),
    )
    return cancels, reason
