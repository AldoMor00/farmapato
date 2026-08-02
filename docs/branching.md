# Ciclo de vida de una rama

Por defecto se trabaja **en el checkout principal** (`portfolio_farmapato/`), con una rama por cambio. Los worktrees son la excepción; ver la última sección.

## 1. Crear

```bash
git switch main
git pull
git switch -c <tipo>/<slug>
```

`<tipo>` es `feat`, `fix`, `chore` o `docs`. El `<slug>` describe el cambio.

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

## 4. Merge — volver a main primero

**Hay que salir de la rama antes de mergear, no después.** `--delete-branch` borra la rama local *y* la remota, pero empieza por la local, y `git branch -d` se niega mientras la rama esté checkouteada (en el principal o en un worktree). Ese fallo aborta el resto: la remota también se queda viva, y el mensaje de error sólo habla de la local, así que es fácil darlo por bueno.

```bash
git switch main
gh pr merge <número> --squash --delete-branch
git pull --prune
```

Hecho en ese orden no queda nada que limpiar: ni rama local ni remota. Comprobarlo con el paso 6.

## 5. Si quedaron ramas colgando

Pasa cuando el merge se hizo desde la interfaz web sin marcar **"Delete branch"**, o cuando `--delete-branch` abortó porque la rama seguía checkouteada.

```bash
git switch main
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
git branch                       # ramas locales
git branch -r                    # ramas remotas conocidas
git worktree list                # worktrees vivos
```

Limpiar:

```bash
git fetch --prune                # refs de ramas ya borradas en GitHub
git worktree prune               # metadata de worktrees borrados a mano
```

Si tras `git fetch --prune` una rama remota sigue apareciendo en `git branch -r`, es que **no** está borrada en GitHub. Confirmarlo antes de asumir que es una ref muerta:

```bash
gh api repos/<owner>/<repo>/branches --jq '.[].name'
```

## Cuándo usar un worktree

Sólo cuando hacen falta **dos árboles de trabajo vivos a la vez**:

- Dos cambios abiertos en paralelo, sin querer hacer stash del que está a medias.
- Agentes corriendo en paralelo (si el agente crea su propio checkout aislado, no hace falta añadir uno a mano).
- Revisar o probar una rama ajena sin tocar la propia.

No para un cambio normal de principio a fin: ahí el coste (otro `uv sync`, copiar los no versionados, acordarse de desmontarlo) no compra nada.

**Restricción del stack**: Postgres es un `container_name` y un volumen compartidos por diseño. Dos ramas no pueden reconstruir la base a la vez — el paralelismo vale para editar y para tests que no toquen la base, no para `make all` simultáneos.

### Crear

```bash
git -C <repo-principal> worktree add ../farmapato-wt/<slug> -b <tipo>/<slug>
cd ../farmapato-wt/<slug> && uv sync
```

El `.venv/` **no se comparte** entre worktrees. Tampoco se heredan los archivos no versionados del directorio principal (`.env`, contexto local); si el trabajo los necesita, copiarlos manualmente.

### Desmontar

Va **antes** del `gh pr merge --delete-branch`, por lo del paso 4: la rama montada en un worktree bloquea `git branch -d` igual que si estuviera checkouteada.

```bash
git -C <repo-principal> worktree remove ../farmapato-wt/<slug>
```

Todo lo de `git worktree` se ejecuta **desde el directorio principal**. La ruta relativa se resuelve contra el cwd, así que lanzarlo desde dentro del worktree busca `farmapato-wt/farmapato-wt/<slug>` y falla con `is not a working tree`. Usar `git -C` evita el problema.

Si el worktree tiene cambios sin commitear, `git worktree remove` falla; revisar qué hay ahí antes de forzar con `--force`. `--force` también borra los archivos ignorados que vivan dentro (`.env`, `data/`): eso es lo normal, pero conviene saberlo.

Si un worktree fue borrado con `rm -rf` en vez de `git worktree remove`, su metadata queda huérfana en `.git/worktrees/` y la rama sigue "en uso"; `git worktree prune` lo resuelve.
