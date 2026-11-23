"""Хранение настроек в JSON-файле рядом с приложением."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Final

from map_overlay.config import Settings
from map_overlay.errors import ConfigError

logger = logging.getLogger(__name__)

TEMP_SUFFIX: Final = ".tmp"


class JsonSettingsStore:
    """Реализация :class:`map_overlay.application.ports.SettingsStore`."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """Путь к файлу настроек."""
        return self._path

    def load(self) -> Settings:
        """Прочитать настройки.

        Raises:
            ConfigError: если файл есть, но испорчен.
        """
        if not self._path.exists():
            logger.info(
                "Файл настроек не найден (%s), используются значения по умолчанию", self._path
            )
            return Settings()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Не удалось прочитать {self._path}: {exc}") from exc
        settings = Settings.from_dict(raw)
        logger.info("Настройки загружены: %s", self._path)
        return settings

    def save(self, settings: Settings) -> None:
        """Записать настройки атомарно: сначала ``.tmp`` с ``fsync``, затем подмена.

        ``fsync`` нужен, чтобы после внезапного выключения на диске остался либо
        старый файл, либо новый, но не пустой. Секретов в настройках нет — только
        координаты точек и привязки клавиш, поэтому права файла не ужесточаются.
        """
        payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._path.with_suffix(TEMP_SUFFIX)
            with temp_path.open("w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temp_path.replace(self._path)
        except OSError as exc:
            raise ConfigError(f"Не удалось сохранить настройки в {self._path}: {exc}") from exc
        logger.info("Настройки сохранены: %s", self._path)
