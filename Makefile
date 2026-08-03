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
.PHONY: help hooks check lint format test all generate load db-up db-down db-reset db-shell

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

test:
	uv run pytest -q

# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
# `all` es la tesis del proyecto hecha comando: el warehouse entero se
# reconstruye de cero desde el Parquet, sin estado que preservar.

all: db-up generate load

generate:
	uv run python -m generator --out data/raw

load:
	uv run python -m loader --src data/raw

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
# initdb: sólo corre cuando el directorio de datos está vacío.
db-reset:
	docker compose down -v
	docker compose up -d --wait

db-shell:
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)
