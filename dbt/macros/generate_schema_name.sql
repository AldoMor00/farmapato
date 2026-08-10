{#
    Por defecto dbt compone <esquema_del_target>_<esquema_custom>, pensado para
    que varios desarrolladores compartan una base sin pisarse los modelos. Aquí
    la base es desechable y de un solo usuario, así que ese prefijo sólo
    produciría `public_staging`. Con esto el esquema custom se usa tal cual, y
    Postgres acaba con raw, staging, intermediate, core y cx — que se lee como
    el diagrama de la arquitectura.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}

{%- endmacro %}
