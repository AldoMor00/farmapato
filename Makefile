# Orquestador local de FarmaPato.
#
# Las recetas se mantienen como comandos directos, sin lógica de shell: GNU Make
# en Windows usa sh.exe si lo encuentra y cmd.exe si no, y no vale la pena que el
# pipeline dependa de cuál de los dos tocó.

# Make no lee el .env por su cuenta. El guion de `-include` evita que falte el
# archivo rompa targets como `check`, que no necesitan la base para nada.
-include .env
export

.DEFAULT_GOAL := help
.PHONY: help hooks check lint format test all generate publish load load-cloud dbt-deps dbt-debug dbt-build db-up db-down db-reset db-shell

# Dónde vive el Parquet. Por defecto el disco local, que es caché de desarrollo;
# la fuente de verdad es la landing zone en ADLS Gen2.
#
# El Parquet va en la raíz del contenedor y no bajo un prefijo `raw/`: el
# contenedor ya es la unidad de significado y de permiso, y `raw` es además el
# nombre del esquema de Postgres, donde quiere decir otra cosa.
RAW ?= data/raw
LANDING = abfss://$(AZURE_CONTAINER_LANDING)@$(AZURE_STORAGE_ACCOUNT).dfs.core.windows.net

# dbt se invoca siempre desde la raíz del repo, así que los dos directorios van
# explícitos. --profiles-dir no es comodidad: en dbt Core el perfil se busca en
# el directorio de trabajo y en Fusion en la raíz del proyecto, y el flag es lo
# único que encabeza el orden de búsqueda en los dos motores.
DBT = uv run dbt
DBT_DIRS = --project-dir dbt --profiles-dir dbt

# `all` encadena pasos que dependen del anterior; con -j Make los lanzaría en
# paralelo y cargaría un Parquet que todavia no existe.
.NOTPARALLEL:

help:
	@echo "FarmaPato - targets disponibles"
	@echo ""
	@echo "  hooks      instala el pre-commit de git (una vez tras clonar)"
	@echo "  check      lint + test (lo mismo que corre CI)"
	@echo "  lint       ruff check y verificacion de formato"
	@echo "  format     aplica formato y arreglos automaticos"
	@echo "  test       pytest del generador y del loader"
	@echo ""
	@echo "  all        reconstruye el warehouse: db-up + generate + load"
	@echo "  generate   escribe las 9 tablas raw en data/raw"
	@echo "  load       carga data/raw al esquema raw de Postgres"
	@echo ""
	@echo "  publish    genera directamente sobre la landing zone en ADLS Gen2"
	@echo "  load-cloud carga a Postgres leyendo desde ADLS Gen2"
	@echo ""
	@echo "  dbt-deps   instala los paquetes de dbt (una vez tras clonar)"
	@echo "  dbt-debug  verifica la conexion y la configuracion de dbt"
	@echo "  dbt-build  corre los modelos y los tests de dbt"
	@echo ""
	@echo "  db-up      levanta Postgres y espera a que este healthy"
	@echo "  db-down    para Postgres (conserva el volumen)"
	@echo "  db-reset   borra el volumen y vuelve a levantar"
	@echo "  db-shell   abre psql contra la base local"

# ---------------------------------------------------------------------------
# Calidad
# ---------------------------------------------------------------------------
# El pre-commit es la garantía que no depende del editor ni del agente. Se
# instala en el directorio de hooks común, así que los worktrees lo heredan.

hooks:
	uv run pre-commit install

check: lint test

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

# -ra imprime el motivo de cada test saltado. Con -q a secas un skip es una `s`
# gris y el resumen dice "passed": así se nota que los tests de ingesta no
# corrieron por falta de FARMAPATO_DB_TESTS=1, en vez de creer que pasaron.
test:
	uv run pytest -q -ra

# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
# `all` es la tesis del proyecto hecha comando: el warehouse entero se
# reconstruye de cero desde el Parquet, sin estado que preservar.

all: db-up generate load

generate:
	uv run python -m generator --out $(RAW)

load:
	uv run python -m loader --src $(RAW)

# Los mismos dos pasos apuntando al lago. La variable específica de target se
# propaga a los prerequisitos, así que no hay recetas duplicadas: `publish` es
# `generate` con otro destino, y `load-cloud` es `load` con otro origen.
publish: RAW := $(LANDING)
publish: generate

load-cloud: RAW := $(LANDING)
load-cloud: load

# ---------------------------------------------------------------------------
# Transformación
# ---------------------------------------------------------------------------
# `deps` va aparte y no como prerequisito de `build`: las dependencias se
# resuelven contra el hub por red, y encadenarlas haría que cada build dependa
# de que el hub esté arriba. Se instalan una vez tras clonar, como `hooks`.

dbt-deps:
	$(DBT) deps $(DBT_DIRS)

dbt-debug:
	$(DBT) debug $(DBT_DIRS)

dbt-build:
	$(DBT) build $(DBT_DIRS)

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
# `--wait` bloquea hasta que el healthcheck del compose pasa: Postgres acepta
# conexiones varios segundos después de que el contenedor existe, y el paso de
# carga no puede salir corriendo antes.

db-up:
	docker compose up -d --wait

db-down:
	docker compose down

# Recrea el volumen. Es también la forma de volver a ejecutar el script de
# initdb —sólo corre cuando el directorio de datos está vacío— y la única de
# aplicar un cambio de DDL sobre tablas que ya existen: el loader reaplica el
# script en cada carga, pero `IF NOT EXISTS` no añade columnas ni altera tipos.
db-reset:
	docker compose down -v
	docker compose up -d --wait

db-shell:
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)
