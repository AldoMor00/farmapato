# FarmaPato — contexto para agentes

Proyecto de portafolio: pipeline de analytics engineering para una farmacia en línea ficticia (FarmaPato). Datos sintéticos de satisfacción del cliente (NPS/CSAT/CES) generados con un modelo causal, modelados en dbt, analizados con regresión logística. Tesis: el protagonista es el warehouse — los datos quedan tan bien modelados que el análisis final es trivial.

## Arquitectura (contrato entre componentes)

```
config.yaml → generador Python → Parquet en ADLS Gen2 (landing zone, única capa durable)
→ carga a Postgres esquema raw (Docker local / service container en CI; efímero)
→ dbt: staging → core (star schema) → marts (métricas CX + ABT point-in-time)
→ Power BI y Quarto leen SOLO de los marts en Postgres, nunca de Azure
```

- Postgres es 100% reconstruible con `make all`; no persistir nada ahí que no salga del pipeline.
- Los componentes se integran por la base de datos, no por imports entre sí.

## Vocabulario

- dbt **transforma** dentro del warehouse; quien **ingiere** es el paso de carga hacia `raw`.
- Postgres aquí funciona como **warehouse analítico**; el esquema `raw` emula sistemas fuente, no es un OLTP.
- Churn **"asociado"** a insatisfacción, nunca "causado": el diseño es observacional.

## Reglas duras

- Package manager: **uv** (nunca pip ni poetry).
- Lint y formato de Python con **ruff** (`uv run ruff check .` y `uv run ruff format .`) antes de cada commit que toque `.py`.
- La ABT se construye en dbt como SQL (window functions, point-in-time); **nunca en pandas**.
- Análisis en Quarto (`.qmd`); **nada de `.ipynb`** en el repo.
- Tests por componente (pytest en `generator/tests/`, tests de dbt en `dbt/`); no hay `/tests` raíz.
- Nunca credenciales ni cadenas de conexión en el repo: `.env` (ignorado) local, OIDC en CI.

## Git

- Trunk-based, ramas cortas: `feat/`, `fix/`, `chore/`, `docs/` + scope.
- Conventional commits con scope de componente: `feat(dbt): ...`, `fix(generator): ...`, `chore(ci): ...`.
- **Nunca** merge de main hacia la rama; si quedó atrás, `git rebase main`. Merge solo rama → main vía PR.
- PRs pequeñas y atómicas; si un cambio rompe un contrato entre componentes, el fix de ambos lados va junto.
