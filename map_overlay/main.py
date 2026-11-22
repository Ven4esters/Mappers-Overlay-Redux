"""Точка входа Map Overlay Redux."""

from __future__ import annotations

import argparse
import logging
import platform
import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from map_overlay import __version__
from map_overlay.application.ports import PanelAutomation
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.fields import PANEL_ORDER
from map_overlay.errors import AppError, ConfigError
from map_overlay.infrastructure.clipboard import SystemClipboard
from map_overlay.infrastructure.clock import SystemClock
from map_overlay.infrastructure.panel import CalibratedPanel
from map_overlay.infrastructure.settings_store import JsonSettingsStore
from map_overlay.infrastructure.win32_input import WindowsInput, enable_dpi_awareness
from map_overlay.logging_setup import setup_logging
from map_overlay.paths import log_path, settings_path
from map_overlay.ui.theme import APP_QSS
from map_overlay.ui.window import MainWindow

logger = logging.getLogger(__name__)

APP_NAME = "Map Overlay Redux"


def main(argv: Sequence[str] | None = None) -> int:
    """Запустить оверлей. Возвращает код выхода."""
    args = _parse_args(argv)
    if enable_dpi_awareness():
        logger.debug("Включён режим Per-Monitor V2")
    setup_logging(log_path(), debug=args.debug, console=args.debug)
    logger.info("Старт %s %s на Python %s", APP_NAME, __version__, platform.python_version())
    if args.check_only:
        return _check_only()
    try:
        return _run_window()
    except AppError as exc:
        logger.error("Запуск невозможен: %s", exc)
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


def _run_window() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyleSheet(APP_QSS)

    store = JsonSettingsStore(settings_path())
    input_port = WindowsInput()

    def panel_factory(settings: Settings) -> PanelAutomation:
        return CalibratedPanel(
            input_port=input_port,
            clipboard=SystemClipboard(),
            clock=SystemClock(),
            points=settings.calibration,
            delays=settings.delays,
        )

    context = AppContext(
        store=store,
        cursor=input_port,
        panel_factory=panel_factory,
        config_path=store.path,
    )
    window = MainWindow(context)
    window.show()
    return int(app.exec())


def _check_only() -> int:
    store = JsonSettingsStore(settings_path())
    print(f"{APP_NAME} {__version__}")
    print(f"Python {platform.python_version()}, {platform.system()}")
    print(f"Настройки: {store.path}")
    try:
        settings = store.load()
    except ConfigError as exc:
        print(f"Настройки не читаются: {exc}")
        return 2
    calibrated = len([field for field in PANEL_ORDER if field in settings.calibration])
    print(f"Калибровка: {calibrated}/{len(PANEL_ORDER)}")
    print(f"Журнал: {log_path()}")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Оверлей для мапперов LSP")
    parser.add_argument("--check-only", action="store_true", help="проверить окружение и выйти")
    parser.add_argument("--debug", action="store_true", help="подробный журнал и вывод в консоль")
    return parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
