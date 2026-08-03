-- Esquema `raw`: emula los sistemas fuente de FarmaPato.
--
-- Aquí aterriza el Parquet de la landing zone tal como salió del generador,
-- con su suciedad intacta (duplicados, escalas mezcladas, timestamps sin
-- offset). La limpieza es trabajo de dbt en staging, no de la ingesta.
--
-- Este archivo es la única fuente de verdad del esquema. Lo aplica el paso de
-- carga en cada corrida (`python -m loader`), por eso todo va escrito como IF
-- NOT EXISTS. Sigue además montado en /docker-entrypoint-initdb.d/, pero eso es
-- redundancia: initdb sólo corre cuando el volumen se crea de cero, así que si
-- fuera el único camino, editar este archivo exigiría un `make db-reset`.
--
-- Nada de PRIMARY KEY, FOREIGN KEY, NOT NULL ni CHECK. `raw` es landing zone,
-- no un OLTP: aquí aterriza lo que mandó el sistema fuente, con sus duplicados
-- y sus centinelas. Una constraint sólo lograría que la carga reventara con
-- datos que *deben* entrar sucios. Validar es trabajo de dbt.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.customers (
    customer_id       bigint,
    nombre_completo   text,
    email             text,
    fecha_alta        date,
    ciudad            text,
    anio_nacimiento   integer,
    canal_adquisicion text,
    canal_preferido   text
);

CREATE TABLE IF NOT EXISTS raw.products (
    product_id      bigint,
    categoria       text,
    precio          double precision,
    requiere_receta boolean
);

CREATE TABLE IF NOT EXISTS raw.subscriptions (
    subscription_id    bigint,
    customer_id        bigint,
    condicion          text,
    fecha_inicio       date,
    fecha_cancelacion  date,
    motivo_cancelacion text,
    valor_mensual      double precision,
    frecuencia         text
);

CREATE TABLE IF NOT EXISTS raw.orders (
    order_id     bigint,
    customer_id  bigint,
    fecha_pedido date,
    canal        text,
    tipo         text,
    monto        double precision
);

CREATE TABLE IF NOT EXISTS raw.order_items (
    order_id    bigint,
    product_id  bigint,
    cantidad    integer,
    fill_status text
);

CREATE TABLE IF NOT EXISTS raw.deliveries (
    delivery_id     bigint,
    order_id        bigint,
    fecha_prometida date,
    fecha_entrega   date,
    estatus         text
);

-- created_at y resolved_at van como TEXTO a propósito: tres sistemas fuente
-- escriben la hora de tres maneras (UTC con sufijo Z, local con offset, y naive
-- sin marca). Tiparlas aquí resolvería en la ingesta el problema que staging
-- tiene que resolver — y fallaría al parsear.
CREATE TABLE IF NOT EXISTS raw.tickets (
    ticket_id   bigint,
    customer_id bigint,
    order_id    bigint,
    categoria   text,
    canal       text,
    created_at  text,
    resolved_at text
);

CREATE TABLE IF NOT EXISTS raw.survey_invitations (
    invitation_id        bigint,
    customer_id          bigint,
    tipo                 text,
    id_evento_disparador bigint,
    fecha_envio          text,
    canal                text
);

-- fecha_respuesta sí es timestamp: esta columna la escribe un solo proveedor y
-- llega limpia. El contraste con las de arriba es deliberado.
CREATE TABLE IF NOT EXISTS raw.survey_responses (
    invitation_id   bigint,
    fecha_respuesta timestamp,
    score           bigint,
    verbatim        text
);
