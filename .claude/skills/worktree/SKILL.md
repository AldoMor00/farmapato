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

## 4. Merge

```bash
gh pr merge --squash --delete-branch
```

`--delete-branch` borra la rama **remota** en GitHub. La local sigue viva y hay que borrarla a mano (paso 5).

Si el merge se hizo desde la interfaz web, hay que marcar el botón **"Delete branch"** que aparece después. Si no se marcó, la rama remota sigue viva y `git fetch --prune` **no** la quita — prune solo borra refs locales de ramas que ya desaparecieron del remoto. Borrarla explícitamente:

```bash
git push origin --delete <tipo>/<slug>
```

## 5. Limpiar — en este orden

El orden importa: `git branch -d` falla si la rama sigue montada en un worktree.

```bash
# 1. Desde el directorio principal, no desde el worktree:
git worktree remove ../farmapato-wt/<slug>

# 2. Traer el merge y podar refs remotas muertas:
git checkout main
git pull --prune

# 3. Borrar la rama local:
git branch -D <tipo>/<slug>
```

**Por qué `-D` y no `-d`**: el squash merge crea un commit nuevo en main que no comparte SHA con los commits de la rama, así que git no la reconoce como fusionada y `-d` se niega. Antes de usar `-D`, confirmar que la PR está en estado merged:

```bash
gh pr view <número> --json state,mergedAt
```

Si el worktree tiene cambios sin commitear, `git worktree remove` falla; revisar qué hay ahí antes de forzar con `--force`.

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
