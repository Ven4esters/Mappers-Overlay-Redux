"""Точка входа: настройки, панель, окно и цикл событий Qt."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from lsp_overlay import __version__
from lsp_overlay.application.session import MappingSession
from lsp_overlay.config import Settings
from lsp_overlay.infrastructure.catalog_store import CatalogStore
from lsp_overlay.infrastructure.clipboard import SystemClipboard
from lsp_overlay.infrastructure.config_store import ConfigStore
from lsp_overlay.infrastructure.global_keys import NullKeyHook, Win32KeyHook
from lsp_overlay.infrastructure.panel import ClipboardPanel
from lsp_overlay.infrastructure.win32_input import (
    NullKeyState,
    Win32InputBackend,
    Win32KeyState,
    enable_dpi_awareness,
)
from lsp_overlay.logging_setup import setup_logging

LOGGER = logging.getLogger(__name__)
DEFAULT_LOG_DIR = Path("logs")
READY_MARKER = "session_ready.txt"
EXIT_OK = 0
EXIT_ENVIRONMENT = 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(prog="lsp-overlay", description="Оверлей для мапперов LSP")
    parser.add_argument("--version", action="version", version=f"LSP Mapper Overlay {__version__}")
    parser.add_argument("--debug", action="store_true", help="подробные логи")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="куда писать логи")
    parser.add_argument(
        "--check",
        action="store_true",
        help="проверить окружение и настройки, не открывая окно",
    )
    return parser.parse_args(argv)


def build_session(settings: Settings) -> MappingSession:
    """Собирает панель и сессию — без Qt, чтобы это можно было тестировать."""
    panel = ClipboardPanel(
        Win32InputBackend(),
        SystemClipboard(),
        calibration=settings.calibration,
        timings=settings.timings,
        length_decimals=settings.length_decimals,
        confirm_key=settings.confirm_key,
    )
    return MappingSession(panel, settings)


def main(argv: Sequence[str] | None = None) -> int:
    """Запускает приложение и возвращает код выхода."""
    args = parse_args(argv)
    log_path = setup_logging(args.log_dir, debug=args.debug)
    LOGGER.info("Старт LSP Mapper Overlay %s, лог: %s", __version__, log_path)

    store = ConfigStore()
    settings = store.load()

    if args.check:
        return _check(settings, store)

    if enable_dpi_awareness():
        LOGGER.info("Включён режим Per-Monitor V2 DPI (координаты кликов — физические пиксели)")
    else:
        LOGGER.info("DPI awareness не включён (не Windows или старая версия)")

    session = build_session(settings)
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415 - --check работает без Qt

    from lsp_overlay.ui.overlay import OverlayWindow  # noqa: PLC0415 - только для окна

    application = QApplication(sys.argv[:1])
    application.setApplicationName("LSP Mapper Overlay")
    key_state = Win32KeyState() if sys.platform == "win32" else NullKeyState()
    if not key_state.is_ready():
        LOGGER.info("Живой режим: чтение клавиш недоступно (не Windows)")
    elif not key_state.num_lock_enabled():
        LOGGER.warning("NumLock выключен: живой режим не увидит Numpad")
    key_hook = Win32KeyHook() if key_state.is_ready() else NullKeyHook()
    window = OverlayWindow(
        session,
        store,
        settings,
        catalog_store=CatalogStore(),
        key_state=key_state,
        key_hook=key_hook,
    )
    window.show()
    _write_ready_marker(args.log_dir)
    LOGGER.info(
        "Окно готово, калибровка %s", "задана" if settings.calibration.is_complete else "не задана"
    )
    return int(application.exec())


def _write_ready_marker(log_dir: Path) -> None:
    """Сообщает лаунчеру, что окно открылось (``logs/session_ready.txt``)."""
    marker = log_dir / READY_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{__version__} {sys.version.split()[0]}", encoding="utf-8")


def _check(settings: Settings, store: ConfigStore) -> int:
    input_ready = Win32InputBackend().is_ready()
    problems: list[str] = []
    if not input_ready:
        problems.append("ввод Win32 недоступен (нужна Windows)")
    if not settings.calibration.is_complete:
        problems.append("калибровка не завершена")
    print(f"Python {sys.version.split()[0]}")
    print(f"Настройки: {store.path}")
    print(f"Калибровка: {'готова' if settings.calibration.is_complete else 'не готова'}")
    print(f"Ввод: {'готов' if input_ready else 'недоступен'}")
    if problems:
        for problem in problems:
            print(f"- {problem}")
        return EXIT_ENVIRONMENT
    print("Окружение готово")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - запуск как скрипта
    raise SystemExit(main())
