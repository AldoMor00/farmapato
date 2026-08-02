"""Formatea y arregla con ruff el archivo Python que Claude Code acaba de editar.

Lo invoca el hook `PostToolUse` de `.claude/settings.json`, que recibe por stdin
un JSON con la llamada a la herramienta.

**Por qué un script y no un comando suelto.** La versión anterior del hook era
`uv run ruff format . && uv run ruff check --fix .`, y ese `.` es el problema:
los hooks se ejecutan con el directorio principal como cwd, así que mientras se
trabajaba en un worktree bajo `../farmapato-wt/<slug>` el hook formateaba el
directorio principal — donde no había nada que formatear. El worktree acumulaba
código sin formatear y el hook no avisaba de nada.

Aquí se actúa sobre el archivo editado y se busca su `pyproject.toml` subiendo
por sus directorios padre, así que cada worktree usa su propia configuración de
ruff y su propio entorno.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def project_root(path: Path) -> Path | None:
    """El `pyproject.toml` más cercano hacia arriba: el worktree, no el principal."""
    return next((p for p in path.parents if (p / "pyproject.toml").is_file()), None)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    raw_path = payload.get("tool_input", {}).get("file_path")
    if not raw_path:
        return 0

    path = Path(raw_path)
    if path.suffix != ".py" or not path.is_file():
        return 0

    root = project_root(path)
    if root is None:
        return 0

    for args in (["format"], ["check", "--fix"]):
        subprocess.run(
            ["uv", "run", "--project", str(root), "ruff", *args, "--quiet", str(path)],
            check=False,
            capture_output=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
