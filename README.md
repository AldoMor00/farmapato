# FarmaPato 🦆

[![CI](https://github.com/AldoMor00/farmapato/actions/workflows/ci.yml/badge.svg)](https://github.com/AldoMor00/farmapato/actions/workflows/ci.yml)

> **Empresa ficticia.** FarmaPato no existe; todos los datos son sintéticos, generados con un modelo causal parametrizado y reproducible. Ninguna persona ni transacción real aparece en este proyecto.

Pipeline de analytics engineering de punta a punta para una farmacia en línea mexicana ficticia: datos de satisfacción del cliente (NPS, CSAT, CES) generados, modelados y analizados hasta llegar a una cifra de negocio — el ingreso recurrente en riesgo por churn de detractores.

## Arquitectura

```
config.yaml → Generador Python (simula sistemas fuente, datos sucios)
        ↓ escribe Parquet
ADLS Gen2 · contenedor landing  (dato crudo; capa durable)
        ↓ ingesta
Postgres, esquema raw  (Docker local; service container en CI; efímero)
        ↓
dbt staging  (limpieza, tipado, dedupe, tests)
        ↓
dbt intermediate  (entidades unidas, un grano cada una)
        ↓
dbt marts/core: star schema  (hechos y dimensiones)
        ↓                          ↓
marts/cx: métricas CX        marts/cx: ABT point-in-time
        ↓ export                   ↓ export
ADLS Gen2 · contenedor serving  (capa de servicio)
        ↓                          ↓
Power BI (dashboard)         Quarto: linkage analysis
```

El lago se lee en **los dos extremos**, y son dos contenedores en vez de dos carpetas por una razón concreta: el permiso sobre datos se otorga por contenedor, así que separarlos es lo que permite que quien consume los marts no obtenga acceso al dato crudo. Postgres queda como motor de transformación y no como servidor de datos — nada lo consume directamente, y `make all` lo reconstruye entero.

Las capas de dbt llevan los nombres de dbt. Si el vocabulario de referencia es medallion, el arco es el mismo: `raw` es bronze, `staging` e `intermediate` son silver, `marts` es gold. Y dentro de `marts` conviven dos formas a propósito, porque **la forma de un mart la decide su consumidor**: `core` es un star schema porque el motor de Power BI lo es, mientras que la ABT es una tabla ancha porque una regresión necesita una matriz de diseño. Ambas salen de los mismos modelos `intermediate`, así que la lógica de negocio se escribe una sola vez.

Dos elecciones que conviene nombrar porque son decisiones y no ausencias. La **orquestación** son `make` y GitHub Actions; en un proceso de producción real sería Airflow o un equivalente, y [`docs/decisiones.md`](docs/decisiones.md) explica qué haría falta para sostenerlo aquí. El **warehouse** es Postgres, pero los modelos de dbt son portables: viven en git y el mismo proyecto correría sobre Fabric, Snowflake o Databricks cambiando el adaptador — dónde se ejecuta dbt es un detalle de configuración, no de arquitectura.

## Documentación

- [`docs/decisiones.md`](docs/decisiones.md) — las alternativas que se descartaron y por qué: orquestadores (Airflow, Data Factory), plataformas de warehouse (Fabric, Databricks, Synapse), snapshots e incrementales en dbt, un solo contenedor en el lago…
- [`docs/azure-oidc.md`](docs/azure-oidc.md) — cómo se autentica CI contra Azure sin un solo secreto en el repo, y cómo se reparte el permiso sobre el lago.
- [`docs/azure-costos.md`](docs/azure-costos.md) — la huella en Azure y el presupuesto que la vigila.
- [`docs/branching.md`](docs/branching.md) — ciclo de vida de una rama en este repo.

🚧 **En construcción** — este README se convertirá en el case study técnico del proyecto.
