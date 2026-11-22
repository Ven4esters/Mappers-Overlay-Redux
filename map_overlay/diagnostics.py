"""Диагностика: падения, необработанные ошибки и зависания.

Журнал ``overlay.log`` пишет то, что приложение делает. Этот модуль отвечает за то,
что оно **не смогло** сделать:

* ``faulthandler`` сохраняет стек, если процесс падает по fatal error;
* ``sys.excepthook`` и ``threading.excepthook`` логируют необработанные исключения
  вместе с трассировкой — раньше они уходили в stderr, которого у окна нет;
* сторож проверяет, что поток интерфейса подаёт признаки жизни: если сердцебиение
  пропало, в журнал попадают стеки всех потоков — по ним видно, где именно зависло.
"""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import time
import traceback
from collections.abc import Mapping
from pathlib import Path
from types import FrameType, TracebackType
from typing import Final, TextIO, cast

logger = logging.getLogger(__name__)

HANG_TIMEOUT_S: Final = 8.0
"""Сколько секунд без сердцебиения считаются зависанием."""

HANG_POLL_S: Final = 1.0
"""Как часто сторож проверяет сердцебиение."""

_crash_stream: TextIO | None = None
_watchdog: HangWatchdog | None = None


def install_crash_handlers(path: Path) -> None:
    """Сохранять фатальные падения и необработанные исключения в отдельный файл."""
    global _crash_stream
    path.parent.mkdir(parents=True, exist_ok=True)
    _crash_stream = path.open("a", encoding="utf-8", buffering=1)
    _write_crash(f"\n=== Запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    faulthandler.enable(file=_crash_stream, all_threads=True)
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_thread


def close_crash_handlers() -> None:
    """Закрыть файл аварий при выходе (и в тестах)."""
    global _crash_stream
    faulthandler.disable()
    if _crash_stream is not None:
        try:
            _crash_stream.close()
        finally:
            _crash_stream = None


def thread_dumps() -> str:
    """Стеки всех потоков: кто где стоит прямо сейчас."""
    frames_getter = getattr(sys, "_current_frames", None)
    if frames_getter is None:
        return "Стеки потоков недоступны в этой версии Python"
    frames: Mapping[int, FrameType] = cast("Mapping[int, FrameType]", frames_getter())
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    parts: list[str] = []
    for ident, frame in frames.items():
        name = names.get(ident, "?")
        stack = "".join(traceback.format_stack(frame))
        parts.append(f"--- поток {name} ({ident}) ---\n{stack}")
    return "\n".join(parts)


class HangWatchdog:
    """Сторож зависаний: ждёт сердцебиение интерфейса и пишет стеки потоков."""

    def __init__(self, *, timeout_s: float = HANG_TIMEOUT_S, poll_s: float = HANG_POLL_S) -> None:
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._last_beat = time.monotonic()
        self._stalled = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def stalled(self) -> bool:
        """Считается ли приложение зависшим прямо сейчас."""
        with self._lock:
            return self._stalled

    def beat(self) -> None:
        """Отметить, что интерфейс жив."""
        with self._lock:
            self._last_beat = time.monotonic()

    def check_once(self) -> bool:
        """Одна проверка. Возвращает ``True``, если зависание обнаружено только что."""
        with self._lock:
            elapsed = time.monotonic() - self._last_beat
            stalled = self._stalled
        if elapsed > self._timeout_s and not stalled:
            with self._lock:
                self._stalled = True
            message = f"Интерфейс не отвечает {elapsed:.1f} с — стеки потоков:"
            logger.critical("%s\n%s", message, thread_dumps())
            _write_crash(f"{message}\n{thread_dumps()}\n")
            return True
        if elapsed <= self._timeout_s and stalled:
            with self._lock:
                self._stalled = False
            logger.warning("Интерфейс снова отвечает (пауза была %.1f с)", elapsed)
        return False

    def start(self) -> None:
        """Запустить проверку в фоновом потоке."""
        self._thread = threading.Thread(target=self._run, name="overlay-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Остановить сторожа."""
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._poll_s):
            self.check_once()


def start_watchdog(timeout_s: float = HANG_TIMEOUT_S) -> HangWatchdog:
    """Запустить сторож зависаний (один на процесс)."""
    global _watchdog
    if _watchdog is None:
        _watchdog = HangWatchdog(timeout_s=timeout_s)
        _watchdog.start()
        logger.info("Сторож зависаний запущен: порог %.0f с", timeout_s)
    return _watchdog


def stop_watchdog() -> None:
    """Остановить сторож, если он запущен."""
    global _watchdog
    if _watchdog is not None:
        _watchdog.stop()
        _watchdog = None


def beat() -> None:
    """Отметить сердцебиение интерфейса (вызывается по таймеру)."""
    if _watchdog is not None:
        _watchdog.beat()


def _write_crash(text: str) -> None:
    if _crash_stream is None:
        return
    try:
        _crash_stream.write(text)
        _crash_stream.flush()
    except Exception:
        pass


def _log_uncaught(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    """Залогировать исключение, которое никто не поймал."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    logger.critical("Необработанная ошибка:\n%s", text)
    _write_crash(f"Необработанная ошибка:\n{text}")


def _log_uncaught_thread(args: threading.ExceptHookArgs) -> None:
    """Залогировать исключение, которое убило фоновый поток."""
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    name = args.thread.name if args.thread is not None else "?"
    logger.critical("Необработанная ошибка в потоке %s:\n%s", name, text)
    _write_crash(f"Необработанная ошибка в потоке {name}:\n{text}")
