---
name: worktree
description: Ciclo de vida completo de una rama en este repo usando git worktrees — crear el worktree con su rama, mantenerla al día con rebase, abrir la PR, hacer merge y limpiar (directorio, rama local, rama remota, metadata). Úsalo al empezar un cambio en rama, al cerrar una PR, o cuando haya que hacer pruning de worktrees o ramas viejas.
---

# Ciclo de vida de worktrees

El directorio principal (`portfolio_farmapato/`) se queda **siempre en `main`**. Todo trabajo en rama vive en un worktree bajo `../farmapato-wt/<slug>`.

## 1. Crear

```bash
git -C <repo-principal> worktree add ../farmapato-wt/<slug> -b <tipo>/<slug>
```

`<tipo>` es `feat`, `fix`, `chore` o `docs`. El `<slug>` del directorio y de la rama coinciden para poder rastrearlos.

Después de crear, dentro del worktree:

```bash
uv sync
```

El `.venv/` **no se comparte** entre worktrees. Tampoco se heredan los archivos no versionados del directorio principal (`.env`, `CLAUDE.local.md`, `farmapato_brief.md`); si el trabajo los necesita, copiarlos manualmente.

## 2. Trabajar

Commits atómicos con conventional commits y scope de componente (`feat(dbt):`, `fix(generator):`). Si la rama queda atrás respecto a main:

```bash
git fetch origin
git rebase origin/main
```

**Nunca** `git merge main` hacia la rama.

## 3. Abrir la PR

```bash
git push -u origin <tipo>/<slug>
gh pr create --title "<tipo>(<scope>): <descripción>" --body "..."
```

Cuerpo de la PR: qué cambia, por qué, cómo se probó, screenshot si aplica.

## 4. Merge — quitar el worktree primero

**El worktree se desmonta antes de mergear, no después.** `--delete-branch` borra la rama local *y* la remota, pero empieza por la local, y `git branch -d` se niega mientras la rama siga montada en un worktree. Ese fallo aborta el resto: la remota también se queda viva, y el mensaje de error sólo habla de la local, así que es fácil darlo por bueno.

```bash
git -C <repo-principal> worktree remove ../farmapato-wt/<slug>
gh pr merge <número> --squash --delete-branch
git -C <repo-principal> pull --prune
```

Hecho en ese orden no queda nada que limpiar: ni worktree, ni rama local, ni remota. Comprobarlo con el paso 6.

Todo lo de `git worktree` se ejecuta **desde el directorio principal**. La ruta relativa se resuelve contra el cwd, así que lanzarlo desde dentro del worktree busca `farmapato-wt/farmapato-wt/<slug>` y falla con `is not a working tree`. Usar `git -C` evita el problema.

Si el worktree tiene cambios sin commitear, `git worktree remove` falla; revisar qué hay ahí antes de forzar con `--force`. `--force` también borra los archivos ignorados que vivan dentro (`.env`, `data/`): eso es lo normal, pero conviene saberlo.

## 5. Si quedaron ramas colgando

Pasa cuando el merge se hizo desde la interfaz web sin marcar **"Delete branch"**, o cuando `--delete-branch` abortó porque el worktree seguía montado.

```bash
git worktree remove ../farmapato-wt/<slug>   # si sigue vivo
git checkout main
git pull --prune
git branch -D <tipo>/<slug>                  # la local
git push origin --delete <tipo>/<slug>       # la remota
```

**Por qué `-D` y no `-d`**: el squash merge crea un commit nuevo en main que no comparte SHA con los commits de la rama, así que git no la reconoce como fusionada y `-d` se niega. Antes de usar `-D`, confirmar que la PR está en estado merged:

```bash
gh pr view <número> --json state,mergedAt
```

**`git fetch --prune` no borra la rama remota**: prune sólo elimina refs locales de ramas que ya desaparecieron del remoto. Si la rama sigue en GitHub, hay que borrarla explícitamente con `git push origin --delete`.

## 6. Pruning periódico

Revisar qué quedó colgando:

```bash
git worktree list                # worktrees vivos
git branch                       # ramas locales
git branch -r                    # ramas remotas conocidas
```

Limpiar:

```bash
git worktree prune               # metadata de worktrees borrados a mano
git fetch --prune                # refs de ramas ya borradas en GitHub
```

Si tras `git fetch --prune` una rama remota sigue apareciendo en `git branch -r`, es que **no** está borrada en GitHub. Confirmarlo antes de asumir que es una ref muerta:

```bash
gh api repos/<owner>/<repo>/branches --jq '.[].name'
```

Si un worktree fue borrado con `rm -rf` en vez de `git worktree remove`, su metadata queda huérfana en `.git/worktrees/` y la rama sigue "en uso"; `git worktree prune` lo resuelve.
