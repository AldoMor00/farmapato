-- Esquema `raw`: emula los sistemas fuente de FarmaPato.
--
-- Aquí aterriza el Parquet de la landing zone tal como salió del generador,
-- con su suciedad intacta (duplicados, escalas mezcladas, timestamps sin
-- offset). La limpieza es trabajo de dbt en staging, no de la ingesta.
--
-- Este archivo es la única fuente de verdad del esquema y se invoca en dos
-- lugares: montado en /docker-entrypoint-initdb.d/ para el Postgres local, y
-- ejecutado con psql en CI, donde el service container arranca antes del
-- checkout y por tanto no puede montarlo.
--
-- El DDL de las 9 tablas llega con el paso de carga, no aquí.

CREATE SCHEMA IF NOT EXISTS raw;
