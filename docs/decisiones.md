# Lo que se descartó, y por qué

Lo que un diseño no hace dice más de él que lo que hace, y no se ve en el código. Este documento recoge las alternativas que se consideraron de verdad y el motivo de haberlas dejado fuera.

El proyecto se apoya en tres restricciones que explican casi todo lo de abajo: **presupuesto de 2 USD al mes**, **cero servicios con estado durable fuera del lago**, y **el warehouse tiene que ser reconstruible de cero con un comando**.

## Orquestación

El orquestador de este proyecto son `make` y GitHub Actions. **En un proceso de producción real sería Airflow**, o un equivalente como Prefect o Dagster: es lo que se opera en la industria. No está aquí por una razón concreta y comprobada — nadie hospeda un scheduler siempre encendido gratis dentro de un presupuesto de 2 USD.

Conviene desarmar una analogía falsa antes de que la haga alguien más: **Postgres en un contenedor y Airflow en un contenedor no son el mismo patrón**. Postgres es una *dependencia* — el pipeline la necesita mientras corre y muere después, y eso basta. Airflow es un *scheduler*, y su valor entero está en seguir encendido cuando nadie lo mira. Un Airflow local sería `make` con un servidor web encima.

| Alternativa | Por qué no |
| --- | --- |
| **Azure Data Factory** | Ya hay orquestador: GitHub Actions, en YAML versionado, gratis y con los logs públicos. Y el JSON que genera la UI es auditable pero **no legible** — nadie lo lee en una revisión. El costo **no** fue el motivo: con un trigger semanal ADF costaría centavos al mes. |
| **Airflow autohospedado** (Container Apps) | El free grant son 180,000 vCPU-segundos al mes = **50 vCPU-horas**. Un scheduler encendido 24/7, aun al mínimo de 0.25 vCPU, necesita ~182. Y no puede escalar a cero: un scheduler dormido no agenda nada. |
| **Airflow efímero** dentro del workflow programado | Levantarlo, correr el DAG y tirarlo sí cabría —Actions pondría la agenda y Airflow el grafo—, pero a esta escala añade observabilidad y reintento **por modelo** de dbt, no capacidad nueva: dbt ya resuelve y paraleliza su propio DAG. Es complejidad que se paga en mantenimiento y se cobra en una captura de pantalla. |
| **Managed Airflow en Data Factory** | **Cerrado.** Desde el 1 de enero de 2026 no se pueden crear instancias nuevas, y la página de precios está archivada. |
| **Apache Airflow jobs en Fabric** | El pool consume **5 CU de base** (small) o 10 (large) mientras está corriendo, se usen o no. La capacidad más pequeña, F2, tiene **2 CU**. |
| **Prefect Cloud / Dagster+** | Tienen tiers gratuitos de verdad — el Hobby de Prefect incluye plano de control hospedado y permanente. Pero por el mismo trabajo entregan un keyword que el mercado nombra mucho menos que Airflow. |

## Plataforma de warehouse

El warehouse es Postgres en un contenedor, y la elección es más pequeña de lo que parece: **dónde se ejecuta dbt es un detalle de `profiles.yml`**. Los modelos viven en git, y el mismo proyecto correría sobre Fabric, Snowflake, Databricks o Azure SQL cambiando el adaptador. Postgres está aquí porque es gratis, corre en local, itera rápido, tiene semántica cliente-servidor y `make all` lo reconstruye entero.

| Alternativa | Por qué no |
| --- | --- |
| **Postgres gestionado en la nube** (Neon, Supabase, Flexible Server) | Ahorraría el paso de exportación, pero mete una base **durable y con estado** en un diseño cuya tesis es que Postgres es desechable. Contradice lo construido para ahorrar unas 60 líneas. Y el tier gratuito de Flexible Server tiene fecha: **0 USD durante 12 meses y después ~12 USD/mes** sólo de cómputo, seis veces el presupuesto. |
| **Azure SQL Database** (free offer) | Gratis para siempre y en cualquier suscripción, pero el límite son 100,000 vCore-segundos = **27.8 vCore-horas al mes**, y serverless factura tiempo *online*, no tiempo de consulta: un ciclo de desarrollo con dbt lo agota en días. Además obliga a T-SQL y rompe `make all`. |
| **DuckDB en vez de Postgres** | No por «no ser una base de datos real» — lo es. Se quería **semántica cliente-servidor**: conexiones, roles, una base que existe fuera del proceso que la consulta. Es lo que se opera en producción y es a lo que se conecta una herramienta de BI. |
| **Microsoft Fabric** | La capacidad más pequeña, F2, son 0.36 USD/hora → **262.80 USD/mes** encendida. Pausarla no lo arregla: mientras está pausada **OneLake queda ilegible y el almacenamiento se sigue cobrando**, así que no puede ser capa de servicio; y Direct Lake exige capacidad encendida en cada vista del informe. Sostener el bucle de desarrollo de dbt encima rebasa el presupuesto justo en la fase que más itera. |
| **Databricks Free Edition** | Gratis para siempre, sin caducidad y con `dbt-databricks` de primera clase. Pero no soporta *custom workspace storage locations* y restringe la salida a internet, así que difícilmente puede leer el ADLS de este proyecto. Merece un proyecto propio, no un injerto en este. |
| **Synapse Analytics** | El pool serverless es casi gratis (5 USD/TB, mínimo 10 MB por consulta, sin costo en reposo), pero la plataforma está en **modo mantenimiento**: la inversión nueva va a Fabric. El pool dedicado más pequeño, DW100c, son 1.20 USD/hora. |

Lo que queda abierto es Fabric como **lector** de `serving`, vía un shortcut de OneLake: no reemplaza nada, el pipeline no cambia y con pausado disciplinado son un par de dólares al mes. Va con una regla que hay que fijar antes de construirlo, no después — **el informe publicado nunca se asigna a la capacidad**, porque si vive ahí, pausarla lo rompe.

> Los precios de estas dos secciones se consultaron el **2026-08-06** contra la [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) (pública, sin autenticar), región `eastus2`, en USD. Se fechan a propósito: envejecen, y la página de precios del portal muestra `$-` sin sesión iniciada, que es cómo se cuela un número de blog en un documento.

## Modelado en dbt

Las capas son las de dbt —`staging`, `intermediate`, `marts`— y no `bronze`/`silver`/`gold`. El arco es el mismo y el README lo cuenta como medallion, pero el árbol de directorios sigue la convención de la herramienta que lo ejecuta: un revisor que abre un proyecto de dbt espera encontrar los nombres de dbt.

Dentro de `marts` hay dos formas conviviendo, y la regla que las decide es que **la forma de un mart la fija su consumidor**. `core` es un star schema porque el motor de Power BI es un motor de star schema: VertiPaq comprime claves de dimensión y filtra varios hechos desde una dimensión conforme. `cx` contiene una tabla ancha, la ABT, porque una regresión logística necesita una matriz de diseño. No es una incoherencia: es la misma condición que pone dbt en su propia guía, cuando recomienda desnormalizar **salvo** que haya un semantic layer recomponiendo métricas por encima — y Power BI es exactamente eso.

| Alternativa | Por qué no |
| --- | --- |
| **Snapshots de dbt (SCD2)** | Un snapshot estampa `dbt_valid_from` con la hora de reloj de la corrida y acumula estado entre ejecuciones. Este pipeline se sostiene sobre que `make all` reproduce bytes idénticos desde una semilla —comprobado entre dos máquinas en la PR #19—, y un snapshot lo rompe. Además no capturaría nada: el generador emite estado final, no historia, y `raw` se reconstruye debajo. Lo que SCD2 resuelve —saber qué era cierto en el momento T— sí está resuelto, en la ABT, con window functions y un test contra fuga temporal. *(No confundir con los snapshots versionados de blobs de [`azure-oidc.md` §6](azure-oidc.md); son cosas distintas con el mismo nombre.)* |
| **Modelos incrementales** | La escalera que recomienda dbt es vista → tabla cuando la vista tarda en *consultarse* → incremental cuando la tabla tarda en *construirse*, y avisa explícitamente de no llegar a incremental por defecto. Aquí el build completo tarda segundos. Un `is_incremental()` añadiría una rama de código, una clave única y un problema de datos que llegan tarde, a cambio de nada. El primero en escalar sería `fct_order_items`, por `fecha_pedido`, si el build pasara de un par de minutos. |
| **Semantic Layer / MetricFlow** | La API que lo vuelve consumible es de dbt Cloud, y Power BI no puede leerla desde dbt Core. Serían definiciones de métrica que nadie consulta — la misma «clave declarada que no llega al código» que ya se rechazó con `AZURE_CONTAINER_SERVING`. Las métricas viven donde se pueden verificar: NPS con intervalo de confianza en `mart_nps_series`, el resto en medidas DAX. |
| **`canal` como atributo degenerado** en cada hecho, sin `dim_channel` | El canal aparece en pedidos, tickets e invitaciones. Sin dimensión conforme, un filtro «canal = WhatsApp» necesita tres controles independientes que el lector tiene que mantener sincronizados a mano. Cuatro filas compran el filtrado cruzado. Los dos canales de `dim_customer` —adquisición y preferido— **no** se conectan ahí: el canal por el que ocurre un evento es una dimensión del evento, el canal que un cliente prefiere es un atributo del cliente. Conectarlos obligaría a dimensiones role-playing y `USERELATIONSHIP` sin ganar nada. |

## El lago

| Alternativa | Por qué no |
| --- | --- |
| **Un solo contenedor con carpetas** `raw/` y `marts/` | El scope más fino de un role assignment de datos **es el contenedor**. Con uno solo, quien lee los marts lee también el dato crudo, y el mínimo privilegio pasaría a depender de una convención en vez de la estructura. El reparto de permisos está en [`azure-oidc.md`](azure-oidc.md). |
| **Contenedor público** | Es la mala configuración de manual, y tumbaría entera la historia de seguridad del OIDC. La prueba pública que se quería ya existe sin exponer nada: el **log de Actions**, donde cualquiera ve la corrida verde de `publish.yml`. |
| **CI leyendo del lago** | Perdería las PRs desde forks —GitHub no emite el token OIDC a un fork— y acoplaría *validar código* con *disponibilidad de datos*, produciendo CI en rojo por razones ajenas al cambio. `ci.yml` no pide `id-token: write`, y esa ausencia es la prueba dentro del archivo. |
| **`make all` leyendo del lago** | El camino automático se queda local. El lago se justifica por el lado de la capa de servicio, no por el de la carga: hacer que `all` dependa de la red y de una credencial encarecería el ciclo de desarrollo sin comprar nada. `make load-cloud` existe para ejercitar ese camino a mano. |

## Estructura del repositorio

| Alternativa | Por qué no |
| --- | --- |
| **Agrupar `generator/` y `loader/` bajo una carpeta madre** tipo «andamiaje» | El generador sí es andamiaje; el loader **no** — es la ingesta del diagrama. Meterlos juntos enseñaría lo contrario de lo que son. Dirigir la atención del lector es trabajo del README, no del árbol de directorios. |

## Decisiones documentadas donde se aplican

Para no duplicar el razonamiento, estas viven junto al código o al runbook que gobiernan:

- **No construir snapshots versionados en la landing zone**, y cuál sería el disparador para construirlos: [`azure-oidc.md` §6](azure-oidc.md).
- **No migrar los datos al cambiar de suscripción** — se recalculan, no se mueven: [`azure-costos.md`](azure-costos.md).
- **No usar un git worktree para cada PR**: [`branching.md`](branching.md).
- **No poner constraints ni limpieza en el esquema `raw`**: `AGENTS.md`, «Reglas duras».
