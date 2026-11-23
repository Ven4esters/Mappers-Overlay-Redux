"""Пути приложения: настройки, журналы, корень проекта.

Для тестов и портативных сборок корень можно переопределить переменной окружения
``MAPPERS_OVERLAY_HOME``. Прежнее имя ``MAP_OVERLAY_HOME`` тоже читается — чтобы старые
ярлыки и переносимые профили продолжали работать после переименования приложения.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

HOME_ENV: Final = "MAPPERS_OVERLAY_HOME"
LEGACY_HOME_ENV: Final = "MAP_OVERLAY_HOME"
# Прежнее имя переменной окружения: поддерживаем, чтобы не ломать готовые профили.
CONFIG_FILE: Final = "settings.json"
SIZES_FILE: Final = "sizes.json"
LOG_FILE: Final = "overlay.log"
CRASH_FILE: Final = "crash.log"


def application_dir() -> Path:
    """Папка, рядом с которой лежат ``config`` и ``logs``."""
    override = os.environ.get(HOME_ENV) or os.environ.get(LEGACY_HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def settings_path() -> Path:
    """Файл настроек."""
    return application_dir() / "config" / CONFIG_FILE


def sizes_path() -> Path:
    """Файл библиотеки размеров предметов."""
    return application_dir() / "config" / SIZES_FILE


def log_path() -> Path:
    """Файл журнала работы."""
    return application_dir() / "logs" / LOG_FILE


def crash_path() -> Path:
    """Файл аварий: падения процесса и стеки потоков при зависании."""
    return application_dir() / "logs" / CRASH_FILE
