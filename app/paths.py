"""Portable path resolution. / Портативное разрешение путей.

The application is portable: all state lives next to ``main.py`` unless that
directory is not writable, in which case we fall back to the per-user data
directory provided by the OS (via :func:`app_data_dir`).

Приложение портативное: состояние лежит рядом с ``main.py``, а если каталог
недоступен для записи — рядом с данными пользователя ОС.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent


def _is_writable(path: Path) -> bool:
    try:
        probe = path / ".write_probe"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def app_data_dir() -> Path:
    """Return a writable directory for app state. / Каталог состояния приложения."""
    if _is_writable(BASE_DIR):
        return BASE_DIR
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "screensaver-into-discord"


DATA_DIR: Path = app_data_dir()
CONFIG_FILE: Path = DATA_DIR / "config.json"
HISTORY_FILE: Path = DATA_DIR / "history.json"
CACHE_DIR: Path = DATA_DIR / "cache"
ASSETS_DIR: Path = BASE_DIR / "assets"
I18N_DIR: Path = ASSETS_DIR / "i18n"
OAUTH_CLIENT_FILE: Path = DATA_DIR / "oauth.client.json"
OAUTH_CLIENT_EXAMPLE: Path = BASE_DIR / "oauth.client.example.json"
