"""Пути приложения: настройки, журналы, корень проекта.

Для тестов и портативных сборок корень можно переопределить переменной окружения
``MAP_OVERLAY_HOME``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

HOME_ENV: Final = "MAP_OVERLAY_HOME"
CONFIG_FILE: Final = "settings.json"
LOG_FILE: Final = "overlay.log"


def application_dir() -> Path:
    """Папка, рядом с которой лежат ``config`` и ``logs``."""
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def settings_path() -> Path:
    """Файл настроек."""
    return application_dir() / "config" / CONFIG_FILE


def log_path() -> Path:
    """Файл журнала работы."""
    return application_dir() / "logs" / LOG_FILE
