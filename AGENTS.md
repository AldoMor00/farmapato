# FarmaPato — contexto para agentes

Proyecto de portafolio: pipeline de analytics engineering para una farmacia en línea ficticia (FarmaPato). Datos sintéticos de satisfacción del cliente (NPS/CSAT/CES) generados con un modelo causal, modelados en dbt, analizados con regresión logística. Tesis: el protagonista es el warehouse — los datos quedan tan bien modelados que el análisis final es trivial.

## Arquitectura (contrato entre componentes)

```
config.yaml → generador Python → Parquet
→ landing zone en ADLS Gen2, contenedor `landing`: copia durable del dato crudo
→ carga a Postgres esquema raw (Docker local / service container en CI; efímero)
→ dbt: staging → core (star schema) → marts (métricas CX + ABT point-in-time)
→ export de los marts a ADLS Gen2, contenedor `serving`: capa de servicio
→ Power BI y Quarto leen SOLO de `serving`, nunca de Postgres
```

- **El lago se lee en los dos extremos**, y son dos contenedores, no dos carpetas: `landing` es la zona de aterrizaje del dato crudo, `serving` la capa de servicio. Separarlos es lo que permite separar el acceso — quien consume los marts no necesita, ni obtiene, permiso sobre el dato crudo.
- Postgres es el **motor de transformación, no el servidor de datos**: nada lo consume directamente y `make all` lo reconstruye entero. No persistir nada ahí que no salga del pipeline.
- Los componentes se integran por la base de datos, no por imports entre sí.
- Las alternativas ya evaluadas y descartadas —Data Factory, Fabric, Postgres gestionado, DuckDB, un solo contenedor, CI leyendo del lago— están en `docs/decisiones.md` con su motivo. No volver a proponerlas sin un argumento que ese documento no conteste.

## Vocabulario

- dbt **transforma** dentro del warehouse; quien **ingiere** es el paso de carga hacia `raw`.
- Postgres aquí funciona como **warehouse analítico**; el esquema `raw` emula sistemas fuente, no es un OLTP.
- Churn **"asociado"** a insatisfacción, nunca "causado": el diseño es observacional.

## Reglas duras

- Package manager: **uv** (nunca pip ni poetry).
- El formato lo garantiza un hook de git, no el editor: tras clonar, `uv sync` y `make hooks` (una vez por clon; los worktrees lo heredan).
- El paso de carga **no limpia ni valida**: escribe el Parquet tal cual y `raw` va sin PK, FK, NOT NULL ni CHECK. Tipar, deduplicar y probar es trabajo de dbt; una constraint en `raw` sólo haría fallar la ingesta con datos que deben entrar sucios.
- La ABT se construye en dbt como SQL (window functions, point-in-time); **nunca en pandas**.
- Análisis en Quarto (`.qmd`); **nada de `.ipynb`** en el repo.
- Tests por componente (pytest en `generator/tests/` y `loader/tests/`, tests de dbt en `dbt/`); no hay `/tests` raíz.
- Nunca credenciales ni cadenas de conexión en el repo: `.env` (ignorado) local, OIDC en CI.
- El lago en ADLS Gen2 se autentica **sólo con Entra ID**: el storage account se creó con `--allow-shared-key-access false`, así que no existe llave ni connection string que filtrar. El permiso se otorga por RBAC a una identidad (`az login` en local, OIDC en CI) y el código Python es el mismo en ambos lados: polars resuelve la credencial con `credential_provider="auto"`, que por debajo es `DefaultAzureCredential`.
- El RBAC va siempre con **scope de contenedor, nunca de cuenta**: cada identidad ve sólo el contenedor que le toca, y crear uno nuevo no reparte permisos por accidente.
- `--out` del generador y `--src` del loader aceptan ruta local o URI `abfss://`, y son `str`, nunca `Path`: `Path` colapsa la doble barra del esquema. El disco local es caché de desarrollo; la copia durable del dato crudo vive en `landing`.
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
