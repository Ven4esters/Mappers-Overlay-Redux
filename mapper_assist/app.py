from __future__ import annotations

import argparse
import ctypes
import sys
import traceback

from . import __version__ as APP_VERSION
from .logger import (
    get_logger,
    get_log_file_path,
    install_qt_message_logger,
    log_startup_diagnostics,
    mark_session_ready,
    setup_logging,
)


logger = get_logger("mapper_assist.app")


def _enable_windows_dpi_awareness() -> bool:
    """Per-Monitor DPI Awareness v2 — клики попадают пиксель-в-пиксель при масштабе Windows 125%/150%."""
    if sys.platform != "win32":
        return False
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return True
    except Exception:  # noqa: BLE001
        logger.debug("SetProcessDpiAwarenessContext недоступен, пробуем SetProcessDpiAwareness")
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось включить DPI Awareness — координаты кликов могут смещаться")
            return False


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="lsp-mapper-assist",
        description="Оверлей-помощник маппинга для GTA V FiveM (Los Santos Project)",
    )
    parser.add_argument("--debug", action="store_true", help="Подробный вывод логов в консоль")
    parser.add_argument("--log-dir", default=None, help="Каталог для файлов логов (по умолчанию ./logs)")
    parser.add_argument("--version", action="version", version="LSP Mapper Assist 1.0.0")
    return parser.parse_args(argv)


def _show_fatal_dialog(message: str, log_path: str) -> None:
    """Показывает окно с ошибкой, даже если Qt ещё/уже не может отрисовать интерфейс."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "LSP Mapper Assist — критическая ошибка",
            f"{message}\n\nПодробный лог сохранён в файл:\n{log_path}",
        )
    except Exception:  # noqa: BLE001
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    f"{message}\n\nПодробный лог: {log_path}",
                    "LSP Mapper Assist — критическая ошибка",
                    0x10,
                )
            except Exception:  # noqa: BLE001
                pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    import logging

    setup_logging(
        log_dir=args.log_dir,
        console_level=logging.DEBUG if args.debug else logging.INFO,
    )
    logger.info("Запуск LSP Mapper Assist (аргументы: %s)", sys.argv[1:])

    dpi_ok = _enable_windows_dpi_awareness()
    logger.info("DPI Awareness v2: %s", "включён" if dpi_ok else "недоступен")
    log_startup_diagnostics()

    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:  # noqa: BLE001
        logger.exception("Не удалось импортировать PySide6")
        print(
            "Ошибка: PySide6 не установлен.\n"
            f"Технические детали: {exc}\n"
            "Запустите run_mapper.bat — он сам создаст venv и установит зависимости.",
            file=sys.stderr,
        )
        return 2

    install_qt_message_logger()

    from .ui.main_window import MapperMainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LSP Mapper Assist")
    app.setApplicationDisplayName("LSP Mapper Assist")
    app.setOrganizationName("LSP Mapper Assist")

    def _qt_excepthook(exc_type, exc_value, exc_tb) -> None:
        logger.critical("Необработанное исключение Qt", exc_info=(exc_type, exc_value, exc_tb))
        _show_fatal_dialog(
            f"{exc_type.__name__}: {exc_value}",
            str(get_log_file_path()),
        )

    sys.excepthook = _qt_excepthook

    try:
        window = MapperMainWindow()
        window.show()
        mark_session_ready(APP_VERSION)
        exit_code = app.exec()
        logger.info("Приложение завершено с кодом %d", exit_code)
        return exit_code
    except Exception as exc:  # noqa: BLE001
        logger.critical("Критический сбой при запуске интерфейса", exc_info=True)
        _show_fatal_dialog(
            f"Не удалось запустить интерфейс:\n{exc}\n\n{traceback.format_exc(limit=3)}",
            str(get_log_file_path()),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
