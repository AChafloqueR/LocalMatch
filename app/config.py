"""Cargador mínimo de variables de entorno desde .env (sin dependencias externas).

El README indica `cp .env.example .env`, pero la app nunca leía ese archivo:
os.getenv solo ve las variables ya exportadas en el proceso. Este módulo lo resuelve.
"""
import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path | str = ENV_PATH) -> int:
    """Carga líneas KEY=VALUE de `path` en os.environ.

    Nunca pisa variables ya definidas en el entorno (el shell manda).
    Ignora líneas vacías, comentarios (#) y líneas sin '='.
    Devuelve cuántas variables nuevas cargó.
    """
    p = Path(path)
    if not p.is_file():
        return 0
    loaded = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded
