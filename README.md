# FarmaPato 🦆

[![CI](https://github.com/AldoMor00/farmapato/actions/workflows/ci.yml/badge.svg)](https://github.com/AldoMor00/farmapato/actions/workflows/ci.yml)

> **Empresa ficticia.** FarmaPato no existe; todos los datos son sintéticos, generados con un modelo causal parametrizado y reproducible. Ninguna persona ni transacción real aparece en este proyecto.

Pipeline de analytics engineering de punta a punta para una farmacia en línea mexicana ficticia: datos de satisfacción del cliente (NPS, CSAT, CES) generados, modelados y analizados hasta llegar a una cifra de negocio — el ingreso recurrente en riesgo por churn de detractores.

## Arquitectura

```
config.yaml → Generador Python (simula sistemas fuente, datos sucios)
        ↓ escribe Parquet
ADLS Gen2 — landing zone (única capa durable del pipeline)
        ↓ ingesta
Postgres, esquema raw  (Docker local; service container en CI; efímero)
        ↓
dbt staging  (limpieza, tipado, dedupe, tests)
        ↓
dbt core: star schema  (hechos y dimensiones)
        ↓                          ↓
Mart de métricas CX          Mart de features (ABT point-in-time)
        ↓                          ↓
Power BI (dashboard)         Quarto: linkage analysis
```

🚧 **En construcción** — este README se convertirá en el case study técnico del proyecto.
