from __future__ import annotations

import ctypes
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import sys
import threading
from types import TracebackType


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "mapper_assist.log"

_LOGGING_CONFIGURED = False
_ACTIVE_LOG_FILE: Path = DEFAULT_LOG_FILE


def get_log_file_path() -> Path:
    return _ACTIVE_LOG_FILE


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_ready_marker_path() -> Path:
    return _ACTIVE_LOG_FILE.parent / "session_ready.txt"


def mark_session_ready(app_version: str = "") -> Path | None:
    """Создаёт маркер успешного старта GUI — launcher (run_mapper.bat) ждёт этот файл."""
    marker = get_ready_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        import datetime as _dt
        import os as _os

        marker.write_text(
            f"{_dt.datetime.now().isoformat(timespec='seconds')}\n"
            f"pid={_os.getpid()}\n"
            f"version={app_version}\n",
            encoding="utf-8",
        )
        get_logger("mapper_assist.startup").info("Маркер успешного старта записан: %s", marker)
        return marker
    except Exception:  # noqa: BLE001
        get_logger("mapper_assist.startup").warning("Не удалось записать маркер старта %s", marker)
        return None


def setup_logging(
    log_dir: Path | str | None = None,
    file_level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    force_reconfigure: bool = False,
) -> Path:
    """
    Настраивает централизованное логирование приложения:
      - Подробный лог (DEBUG и выше) с ротацией в logs/mapper_assist.log;
      - Краткий лог (INFO и выше) в консоль;
      - Глобальные перехватчики необработанных исключений в главном и фоновых потоках.
    """
    global _LOGGING_CONFIGURED, _ACTIVE_LOG_FILE

    target_dir = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / "mapper_assist.log"
    _ACTIVE_LOG_FILE = log_file

    root_logger = logging.getLogger("mapper_assist")
    if _LOGGING_CONFIGURED and not force_reconfigure:
        return log_file

    root_logger.setLevel(logging.DEBUG)
    root_logger.propagate = False

    # Очищаем старые обработчики при повторной инициализации (например, в тестах)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(threadName)-18s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=2 * 1024 * 1024,  # 2 МБ на файл
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    _install_exception_hooks(root_logger)
    _LOGGING_CONFIGURED = True

    root_logger.info("=== Сессия логирования запущена: %s ===", log_file)
    return log_file


def _install_exception_hooks(logger: logging.Logger) -> None:
    """Перехватывает необработанные ошибки главного потока и фоновых потоков Python."""
    prev_sys_hook = sys.excepthook

    def _handle_sys_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            prev_sys_hook(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Необработанное исключение в главном потоке!",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        prev_sys_hook(exc_type, exc_value, exc_tb)

    def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        thread_name = args.thread.name if args.thread else "UnknownThread"
        logger.critical(
            "Необработанное исключение в фоновом потоке '%s'!",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _handle_sys_exception
    threading.excepthook = _handle_thread_exception


def install_qt_message_logger() -> None:
    """Перенаправляет внутренние предупреждения и ошибки Qt/PySide6 в общий лог-файл."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception as exc:  # noqa: BLE001
        get_logger("mapper_assist.qt").warning("Не удалось подключить логгер Qt: %s", exc)
        return

    qt_logger = get_logger("mapper_assist.qt")

    def _qt_handler(mode: QtMsgType, _context, message: str) -> None:
        if mode == QtMsgType.QtDebugMsg:
            qt_logger.debug(message)
        elif mode == QtMsgType.QtInfoMsg:
            qt_logger.info(message)
        elif mode == QtMsgType.QtWarningMsg:
            qt_logger.warning(message)
        elif mode == QtMsgType.QtCriticalMsg:
            qt_logger.error(message)
        elif mode == QtMsgType.QtFatalMsg:
            qt_logger.critical(message)
        else:
            qt_logger.info(message)

    qInstallMessageHandler(_qt_handler)


def is_windows_admin() -> bool | None:
    """Возвращает True/False на Windows (запущен ли процесс с правами Администратора), иначе None."""
    if sys.platform != "win32":
        return None
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return None


def log_startup_diagnostics() -> None:
    """Записывает диагностическую сводку о системе и правах при старте приложения."""
    logger = get_logger("mapper_assist.startup")
    admin_state = is_windows_admin()
    logger.info(
        "Система: %s %s (%s) | Python %s (%s)",
        platform.system(),
        platform.release(),
        platform.version(),
        platform.python_version(),
        platform.architecture()[0],
    )
    logger.info("Рабочая директория: %s", Path.cwd())
    if admin_state is not None:
        logger.info("Права Администратора Windows: %s", "ДА" if admin_state else "НЕТ (обычный режим)")
        if not admin_state:
            logger.info(
                "Подсказка: если FiveM запущен от имени Администратора и не видит клики/хоткеи, "
                "запустите run_mapper.bat от имени Администратора."
            )
