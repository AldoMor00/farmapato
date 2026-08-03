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
- El formato lo garantiza un hook de git, no el editor: tras clonar, `uv sync` y `make hooks` (una vez por clon; los worktrees lo heredan).
- La ABT se construye en dbt como SQL (window functions, point-in-time); **nunca en pandas**.
- Análisis en Quarto (`.qmd`); **nada de `.ipynb`** en el repo.
- Tests por componente (pytest en `generator/tests/` y `loader/tests/`, tests de dbt en `dbt/`); no hay `/tests` raíz.
- Nunca credenciales ni cadenas de conexión en el repo: `.env` (ignorado) local, OIDC en CI.
- Las instrucciones del proyecto viven en **este archivo**. La configuración de un agente concreto (`.claude/`) es un adaptador: puede automatizar lo que aquí se declara, nunca contener reglas que no estén aquí.

## Metodología

- NPS = %promotores − %detractores, siempre reportado **con intervalo de confianza y n**. CSAT = % top-2-box en escala 1-5. CES en escala 1-7.
- Distinguir siempre NPS **relacional** (trimestral, por email) de **transaccional** (post-entrega). Nunca mezclarlos en una métrica.
- Modelo principal del linkage: **regresión logística** (pregunta inferencial: coeficientes, errores estándar, odds ratios, IC). GBDT + SHAP solo como robustness check en apéndice — SHAP atribuye predicciones, no permite inferencia.
- Los marts que consume Power BI llevan **contratos de dbt** (columnas y tipos declarados).

## Git

- Trunk-based, ramas cortas: `feat/`, `fix/`, `chore/`, `docs/` + scope.
- Conventional commits con scope de componente: `feat(dbt): ...`, `fix(generator): ...`, `chore(ci): ...`.
- **Nunca** merge de main hacia la rama; si quedó atrás, `git rebase main`. Merge solo rama → main vía PR.
- PRs pequeñas y atómicas; si un cambio rompe un contrato entre componentes, el fix de ambos lados va junto.

### Ramas

Flujo por defecto sobre el checkout principal: `git switch -c <tipo>/<slug>`, commits, PR, y de vuelta a `main` al mergear. Al cerrar una PR hay que dejar limpias la rama local y la remota.

Un **git worktree** bajo `../farmapato-wt/<slug>` es la excepción, no la norma: sirve cuando hacen falta dos árboles vivos a la vez (dos cambios abiertos, agentes en paralelo, revisar una rama ajena sin tocar la propia). Cada worktree necesita su propio `uv sync` y no hereda los archivos no versionados del principal.

Ojo con el paralelismo: Postgres es un contenedor y un volumen compartidos, así que dos ramas no pueden reconstruir la base a la vez.

El runbook completo (crear, rebasar, PR, merge, limpieza y pruning, con y sin worktree) está en `docs/branching.md`.
