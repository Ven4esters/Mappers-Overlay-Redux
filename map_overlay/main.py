"""Точка входа Map Overlay Redux."""

from __future__ import annotations

import argparse
import logging
import platform
import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from map_overlay import __version__, diagnostics
from map_overlay.application.ports import HotkeySource, PanelAutomation
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain import lemmas
from map_overlay.domain.fields import PANEL_ORDER
from map_overlay.errors import AppError, ConfigError
from map_overlay.infrastructure.clipboard import SystemClipboard
from map_overlay.infrastructure.clock import SystemClock
from map_overlay.infrastructure.hotkeys import WindowsHotkeySource
from map_overlay.infrastructure.panel import CalibratedPanel
from map_overlay.infrastructure.settings_store import JsonSettingsStore
from map_overlay.infrastructure.size_store import JsonSizeStore
from map_overlay.infrastructure.win32_input import WindowsInput, enable_dpi_awareness
from map_overlay.logging_setup import setup_logging
from map_overlay.paths import crash_path, log_path, settings_path, sizes_path
from map_overlay.trace import note
from map_overlay.ui.theme import APP_QSS
from map_overlay.ui.window import MainWindow

logger = logging.getLogger(__name__)

APP_NAME = "Map Overlay Redux"


def main(argv: Sequence[str] | None = None) -> int:
    """Запустить оверлей. Возвращает код выхода."""
    args = _parse_args(argv)
    # Сначала журнал: иначе самое первое сообщение (и ошибки старта) уходит в никуда.
    setup_logging(log_path(), debug=args.debug, console=args.debug)
    if enable_dpi_awareness():
        logger.debug("Включён режим Per-Monitor V2")
    logger.info("Старт %s %s на Python %s", APP_NAME, __version__, platform.python_version())
    note(
        "запуск: %s %s, Python %s, подробный журнал: %s, файл: %s",
        APP_NAME,
        __version__,
        platform.python_version(),
        "да" if args.debug else "нет",
        log_path(),
    )
    logger.info(lemmas.describe())
    if args.check_only:
        return _check_only()
    diagnostics.install_crash_handlers(crash_path())
    diagnostics.start_watchdog()
    try:
        return _run_window()
    except AppError as exc:
        logger.error("Запуск невозможен: %s", exc)
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        diagnostics.stop_watchdog()
        diagnostics.close_crash_handlers()


def _run_window() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyleSheet(APP_QSS)

    store = JsonSettingsStore(settings_path())
    size_store = JsonSizeStore(sizes_path())
    input_port = WindowsInput()
    hotkey_source: HotkeySource = WindowsHotkeySource()

    def panel_factory(settings: Settings) -> PanelAutomation:
        return CalibratedPanel(
            input_port=input_port,
            clipboard=SystemClipboard(),
            clock=SystemClock(),
            points=settings.calibration,
            delays=settings.delays,
            empty_point=settings.empty_point,
        )

    context = AppContext(
        store=store,
        cursor=input_port,
        panel_factory=panel_factory,
        hotkeys=hotkey_source,
        config_path=store.path,
        size_store=size_store,
        sizes_path=size_store.path,
    )
    settings = context.settings
    note(
        "настройки: %s; калибровка %d/6; размеров %d; клавиш назначено %d",
        store.path,
        len(settings.calibration),
        len(context.sizes.items),
        sum(1 for vk in settings.hotkeys.values() if vk is not None),
    )
    window = MainWindow(context)
    window.show()
    code = int(app.exec())
    note("выход из приложения, код %d", code)
    return code


def _check_only() -> int:
    store = JsonSettingsStore(settings_path())
    sizes = JsonSizeStore(sizes_path())
    print(f"{APP_NAME} {__version__}")
    print(f"Python {platform.python_version()}, {platform.system()}")
    print(f"Настройки: {store.path}")
    try:
        settings = store.load()
    except ConfigError as exc:
        print(f"Настройки не читаются: {exc}")
        return 2
    calibrated = len([field for field in PANEL_ORDER if field in settings.calibration])
    empty = "есть" if settings.has_confirmation_point() else "нет"
    print(f"Калибровка: {calibrated}/{len(PANEL_ORDER)} · точка для F: {empty}")
    try:
        library = sizes.load()
    except ConfigError as exc:
        print(f"Размеры предметов не читаются: {exc}")
        return 2
    active = library.active_item
    chosen = f" · выбран «{active.name}»" if active is not None else ""
    print(f"Размеры предметов: {len(library.items)}{chosen} ({sizes.path})")
    print(f"Журнал: {log_path()}")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Оверлей для мапперов LSP")
    parser.add_argument("--check-only", action="store_true", help="проверить окружение и выйти")
    parser.add_argument("--debug", action="store_true", help="подробный журнал и вывод в консоль")
    return parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
