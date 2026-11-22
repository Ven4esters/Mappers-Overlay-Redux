"""Композиция приложения: настройки, сессия и зависимости для UI."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from map_overlay.application.ports import CursorPort, PanelAutomation, SettingsStore
from map_overlay.application.session import MappingSession
from map_overlay.application.writer import PoseWriter
from map_overlay.config import Settings
from map_overlay.errors import ConfigError

logger = logging.getLogger(__name__)

# Псевдоним типа: type-выражение (PEP 695) требует Python 3.12, а тесты гоняются и на 3.11.
PanelFactory = Callable[[Settings], PanelAutomation]
"""Фабрика панели под текущие настройки (точки калибровки и задержки)."""


class AppContext:
    """Хранит настройки и собирает сессию под них."""

    def __init__(
        self,
        *,
        store: SettingsStore,
        cursor: CursorPort,
        panel_factory: PanelFactory,
        config_path: Path | None = None,
    ) -> None:
        self._store = store
        self._cursor = cursor
        self._panel_factory = panel_factory
        self._config_path = config_path
        self.settings_error: str | None = None
        try:
            self._settings = store.load()
        except ConfigError as exc:
            logger.error("Настройки не загружены: %s", exc)
            self._settings = Settings()
            self.settings_error = str(exc)

    @property
    def settings(self) -> Settings:
        """Текущие настройки."""
        return self._settings

    @property
    def config_path(self) -> Path | None:
        """Где лежит файл настроек (для подсказки во вкладке)."""
        return self._config_path

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
