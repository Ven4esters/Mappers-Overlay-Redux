"""Хранение библиотеки размеров предметов в JSON-файле рядом с настройками."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Final

from map_overlay.domain.sizes import SizeLibrary
from map_overlay.errors import ConfigError

logger = logging.getLogger(__name__)

TEMP_SUFFIX: Final = ".tmp"


class JsonSizeStore:
    """Реализация :class:`map_overlay.application.ports.SizeStore`."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """Путь к файлу библиотеки."""
        return self._path

    def load(self) -> SizeLibrary:
        """Прочитать библиотеку.

        Raises:
            ConfigError: если файл есть, но испорчен.
        """
        if not self._path.exists():
            logger.info("Библиотека размеров не найдена (%s): она пуста", self._path)
            return SizeLibrary()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Не удалось прочитать {self._path}: {exc}") from exc
        library = SizeLibrary.from_dict(raw)
        logger.info("Библиотека размеров загружена: предметов %d", len(library.items))
        return library

    def save(self, library: SizeLibrary) -> None:
        """Записать библиотеку атомарно: ``.tmp`` с ``fsync``, затем подмена.

        Raises:
            ConfigError: если запись не удалась.
        """
        payload = json.dumps(library.to_dict(), ensure_ascii=False, indent=2)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._path.with_suffix(TEMP_SUFFIX)
            with temp_path.open("w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temp_path.replace(self._path)
        except OSError as exc:
            raise ConfigError(f"Не удалось сохранить размеры в {self._path}: {exc}") from exc
        logger.info("Библиотека размеров сохранена: %s", self._path)
