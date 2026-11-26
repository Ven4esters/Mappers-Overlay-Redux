"""Композиция приложения: настройки, сессия и зависимости для UI."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from map_overlay.application.ports import (
    CursorPort,
    HotkeySource,
    PanelAutomation,
    SettingsStore,
    SizeStore,
)
from map_overlay.application.session import MappingSession
from map_overlay.application.writer import PoseWriter
from map_overlay.config import Settings
from map_overlay.domain.sizes import SizeLibrary
from map_overlay.errors import ConfigError

logger = logging.getLogger(__name__)

# Псевдоним типа: type-выражение (PEP 695) требует Python 3.12, а тесты гоняются и на 3.11.
PanelFactory = Callable[[Settings], PanelAutomation]
# Фабрика панели под текущие настройки (точки калибровки и задержки).


class AppContext:
    """Хранит настройки и собирает сессию под них."""

    def __init__(
        self,
        *,
        store: SettingsStore,
        cursor: CursorPort,
        panel_factory: PanelFactory,
        hotkeys: HotkeySource,
        config_path: Path | None = None,
        size_store: SizeStore | None = None,
        sizes_path: Path | None = None,
    ) -> None:
        self._store = store
        self._cursor = cursor
        self._panel_factory = panel_factory
        self._hotkeys = hotkeys
        self._config_path = config_path
        self._size_store = size_store
        self._sizes_path = sizes_path
        self.settings_error: str | None = None
        self.sizes_error: str | None = None
        try:
            self._settings = store.load()
        except ConfigError as exc:
            logger.error("Настройки не загружены: %s", exc)
            self._settings = Settings()
            self.settings_error = str(exc)
        self._sizes = SizeLibrary()
        if size_store is not None:
            try:
                self._sizes = size_store.load()
            except ConfigError as exc:
                # Библиотека размеров — не жизненно важные данные: работаем с пустой.
                logger.error("Размеры предметов не загружены: %s", exc)
                self.sizes_error = str(exc)

    @property
    def settings(self) -> Settings:
        """Текущие настройки."""
        return self._settings

    @property
    def config_path(self) -> Path | None:
        """Где лежит файл настроек (для подсказки во вкладке)."""
        return self._config_path

    @property
    def sizes(self) -> SizeLibrary:
        """Библиотека размеров предметов."""
        return self._sizes

    @property
    def sizes_path(self) -> Path | None:
        """Где лежит файл размеров (для подсказки во вкладке)."""
        return self._sizes_path

    @property
    def hotkeys(self) -> HotkeySource:
        """Источник глобальных горячих клавиш."""
        return self._hotkeys

    @property
    def cursor(self) -> CursorPort:
        """Курсор для калибровки."""
        return self._cursor

    def make_session(self) -> MappingSession:
        """Собрать сессию по текущим настройкам."""
        panel = self._panel_factory(self._settings)
        writer = PoseWriter(
            panel, decimals=self._settings.decimals, verify=self._settings.verify_writes
        )
        return MappingSession(panel, writer)

    def save_settings(self, settings: Settings) -> None:
        """Сохранить настройки и применять их дальше.

        Raises:
            ConfigError: если запись не удалась.
        """
        self._store.save(settings)
        self._settings = settings

    def save_sizes(self, library: SizeLibrary) -> None:
        """Сохранить библиотеку размеров и применять её дальше.

        Raises:
            ConfigError: если запись не удалась.
        """
        if self._size_store is not None:
            self._size_store.save(library)
        self._sizes = library
