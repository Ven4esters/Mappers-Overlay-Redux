"""Хранение каталога предметов в JSON рядом с настройками."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from lsp_overlay.config import ConfigError
from lsp_overlay.domain.catalog import Catalog

LOGGER = logging.getLogger(__name__)
CATALOG_ENV = "LSP_OVERLAY_CATALOG"
APP_DIR_NAME = "LSPMapperOverlay"
CATALOG_FILE_NAME = "objects.json"


def default_catalog_path() -> Path:
    """Путь к каталогу: рядом с настройками, ``%APPDATA%`` на Windows."""
    override = os.environ.get(CATALOG_ENV)
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / APP_DIR_NAME / CATALOG_FILE_NAME


class CatalogStore:
    """Читает и пишет каталог; повреждённый файл откладывает в сторону."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_catalog_path()

    @property
    def path(self) -> Path:
        """Где лежит файл каталога."""
        return self._path

    def load(self) -> Catalog:
        """Возвращает каталог из файла или пустой."""
        if not self._path.exists():
            LOGGER.info("Каталог предметов не найден, начинаем с пустого")
            return Catalog()
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
            return Catalog.from_dict(raw)
        except (OSError, json.JSONDecodeError, ConfigError, TypeError, ValueError):
            LOGGER.exception("Не удалось прочитать каталог из %s", self._path)
            self._quarantine()
            return Catalog()

    def save(self, catalog: Catalog) -> None:
        """Атомарно сохраняет каталог."""
        payload = json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self._path)
        LOGGER.debug("Каталог сохранён: %s (%d предметов)", self._path, len(catalog.objects))

    def _quarantine(self) -> None:
        broken = self._path.with_suffix(".broken.json")
        try:
            self._path.replace(broken)
            LOGGER.warning("Повреждённый каталог сохранён как %s", broken)
        except OSError:
            LOGGER.exception("Не удалось переименовать повреждённый каталог")
