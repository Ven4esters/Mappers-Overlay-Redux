"""Диагностика: стеки потоков, сторож зависаний и журнал необработанных ошибок."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from map_overlay import diagnostics


def test_thread_dumps_show_the_calling_thread() -> None:
    dumps = diagnostics.thread_dumps()
    assert "поток" in dumps
    assert "test_thread_dumps_show_the_calling_thread" in dumps


def test_beat_without_watchdog_is_harmless() -> None:
    diagnostics.stop_watchdog()
    diagnostics.beat()


def test_watchdog_reports_a_hang_and_recovery(caplog: logging.LogRecord) -> None:
    watchdog = diagnostics.HangWatchdog(timeout_s=0.01, poll_s=10.0)
    time.sleep(0.02)
    with caplog.at_level(logging.CRITICAL):
        assert watchdog.check_once() is True
    assert watchdog.stalled is True
    assert "не отвечает" in caplog.text
    watchdog.beat()
    with caplog.at_level(logging.WARNING):
        assert watchdog.check_once() is False
    assert watchdog.stalled is False
    assert "снова отвечает" in caplog.text


def test_watchdog_reports_only_once_per_hang(caplog: logging.LogRecord) -> None:
    watchdog = diagnostics.HangWatchdog(timeout_s=0.01, poll_s=10.0)
    time.sleep(0.02)
    with caplog.at_level(logging.CRITICAL):
        assert watchdog.check_once() is True
        assert watchdog.check_once() is False
    assert caplog.text.count("не отвечает") == 1


def test_started_watchdog_beats() -> None:
    watchdog = diagnostics.start_watchdog(timeout_s=5.0)
    diagnostics.beat()
    assert watchdog.stalled is False
    diagnostics.stop_watchdog()


def test_uncaught_error_goes_to_log_and_crash_file(
    tmp_path: Path, caplog: logging.LogRecord
) -> None:
    crash = tmp_path / "crash.log"
    old_hooks = (sys.excepthook, threading.excepthook)
    try:
        diagnostics.install_crash_handlers(crash)
        with caplog.at_level(logging.CRITICAL):
            sys.excepthook(ValueError, ValueError("boom"), None)
        text = crash.read_text(encoding="utf-8")
    finally:
        diagnostics.close_crash_handlers()
        sys.excepthook, threading.excepthook = old_hooks
    assert "boom" in caplog.text
    assert "boom" in text


def test_uncaught_thread_error_is_logged(tmp_path: Path, caplog: logging.LogRecord) -> None:
    crash = tmp_path / "crash.log"
    old_hooks = (sys.excepthook, threading.excepthook)
    try:
        diagnostics.install_crash_handlers(crash)
        with caplog.at_level(logging.CRITICAL):
            threading.excepthook(
                threading.ExceptHookArgs((ValueError, ValueError("поток упал"), None, None))
            )
    finally:
        diagnostics.close_crash_handlers()
        sys.excepthook, threading.excepthook = old_hooks
    assert "поток упал" in caplog.text


def test_crash_file_is_rotated_when_it_grows(tmp_path: Path) -> None:
    """Прошлый файл аварий сохраняется отдельно, а не копится годами."""
    crash = tmp_path / "crash.log"
    crash.write_bytes(b"x" * (diagnostics.CRASH_MAX_BYTES + 10))
    diagnostics.install_crash_handlers(crash)
    try:
        rotated = crash.with_suffix(".log.1")
        assert rotated.exists()
        assert rotated.stat().st_size > diagnostics.CRASH_MAX_BYTES
        assert crash.stat().st_size < diagnostics.CRASH_MAX_BYTES
    finally:
        diagnostics.close_crash_handlers()
