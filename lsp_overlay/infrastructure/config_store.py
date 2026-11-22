"""Хранение настроек в JSON-файле рядом с профилем пользователя."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from lsp_overlay.config import ConfigError, Settings

LOGGER = logging.getLogger(__name__)
CONFIG_ENV = "LSP_OVERLAY_CONFIG"
APP_DIR_NAME = "LSPMapperOverlay"
CONFIG_FILE_NAME = "settings.json"


def default_config_path() -> Path:
    """Путь к файлу настроек: ``%APPDATA%`` на Windows, ``~/.config`` иначе."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / APP_DIR_NAME / CONFIG_FILE_NAME


class ConfigStore:
    """Читает и пишет настройки; повреждённый файл откладывает в сторону."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_config_path()

    @property
    def path(self) -> Path:
        """Где лежит файл настроек."""
        return self._path

    def load(self) -> Settings:
        """Возвращает настройки из файла или значения по умолчанию."""
        if not self._path.exists():
            LOGGER.info("Файл настроек не найден, используем значения по умолчанию")
            return Settings()
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
            return Settings.from_dict(raw)
        except (OSError, json.JSONDecodeError, ConfigError, TypeError, ValueError):
            LOGGER.exception("Не удалось прочитать настройки из %s", self._path)
            self._quarantine()
            return Settings()

    def save(self, settings: Settings) -> None:
        """Атомарно сохраняет настройки."""
        payload = json.dumps(settings.validated().to_dict(), ensure_ascii=False, indent=2)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self._path)
        LOGGER.debug("Настройки сохранены: %s", self._path)

    def _quarantine(self) -> None:
        broken = self._path.with_suffix(".broken.json")
        try:
            self._path.replace(broken)
            LOGGER.warning("Повреждённый файл настроек сохранён как %s", broken)
        except OSError:
            LOGGER.exception("Не удалось переименовать повреждённый файл настроек")
