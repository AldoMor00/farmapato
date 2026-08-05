# Lo que se descartó, y por qué

Lo que un diseño no hace dice más de él que lo que hace, y no se ve en el código. Este documento recoge las alternativas que se consideraron de verdad y el motivo de haberlas dejado fuera.

El proyecto se apoya en tres restricciones que explican casi todo lo de abajo: **presupuesto de 2 USD al mes**, **cero servicios con estado durable fuera del lago**, y **el warehouse tiene que ser reconstruible de cero con un comando**.

## Orquestación y cómputo

| Alternativa | Por qué no |
| --- | --- |
| **Azure Data Factory** | Cobra por pipeline **inactivo** (~1 USD/mes) y se comería medio presupuesto sin ejecutar nada. Además el JSON que genera la UI es auditable pero **no legible** — nadie lo lee en una revisión. Y ya hay orquestador: GitHub Actions, en YAML versionado, gratis y con los logs públicos. |
| **Fabric / Synapse** | El mismo razonamiento con peor precio. |
| **Postgres gestionado en la nube** (Neon, Supabase, Flexible Server) | Ahorraría el paso de exportación, pero mete una base **durable y con estado** en un diseño cuya tesis es que Postgres es desechable. Contradice lo construido para ahorrar unas 60 líneas. |
| **DuckDB en vez de Postgres** | No por «no ser una base de datos real» — lo es. Se quería **semántica cliente-servidor**: conexiones, roles, una base que existe fuera del proceso que la consulta. Es lo que se opera en producción y es a lo que se conecta una herramienta de BI. |

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
