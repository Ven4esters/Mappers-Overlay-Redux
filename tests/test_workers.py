"""Фоновые задачи: поток, ошибки и занятость."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from map_overlay.errors import ApplicationError, NotCalibratedError
from map_overlay.ui.tasks import TaskRunner
from PySide6.QtWidgets import QApplication


def wait_for(
    qt_app: QApplication, predicate: Callable[[], bool], *, timeout_s: float = 3.0
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_work_runs_in_thread_and_reports_result(qt_app: QApplication) -> None:
    runner = TaskRunner()
    results: list[object] = []
    errors: list[str] = []
    runner.submit(
        lambda: 42,
        on_success=results.append,
        on_error=errors.append,
    )
    assert wait_for(qt_app, lambda: bool(results))
    assert results == [42]
    assert errors == []
    assert wait_for(qt_app, lambda: not runner.is_busy())


def test_expected_error_is_shown_as_is(qt_app: QApplication) -> None:
    runner = TaskRunner()
    errors: list[str] = []

    def work() -> object:
        raise NotCalibratedError("Не откалибровано поле X")

    runner.submit(work, on_success=lambda _result: None, on_error=errors.append)
    assert wait_for(qt_app, lambda: bool(errors))
    assert errors == ["Не откалибровано поле X"]
    assert wait_for(qt_app, lambda: not runner.is_busy())
    runner.shutdown()


def test_unexpected_error_becomes_internal_error(qt_app: QApplication) -> None:
    runner = TaskRunner()
    errors: list[str] = []

    def work() -> object:
        raise ValueError("boom")

    runner.submit(work, on_success=lambda _result: None, on_error=errors.append)
    assert wait_for(qt_app, lambda: bool(errors))
    assert errors[0].startswith("Внутренняя ошибка")
    assert wait_for(qt_app, lambda: not runner.is_busy())
    runner.shutdown()


def test_second_task_is_refused_while_busy(qt_app: QApplication) -> None:
    runner = TaskRunner()
    errors: list[str] = []
    runner.submit(
        lambda: time.sleep(0.15),
        on_success=lambda _result: None,
        on_error=errors.append,
    )
    assert runner.is_busy()
    runner.submit(lambda: 1, on_success=lambda _result: None, on_error=errors.append)
    assert errors == ["Дождитесь окончания предыдущего действия"]
    assert wait_for(qt_app, lambda: not runner.is_busy())
    runner.shutdown()


def test_synchronous_runner_reports_errors_immediately() -> None:
    runner = TaskRunner(synchronous=True)
    errors: list[str] = []

    def work() -> object:
        raise ApplicationError("нет калибровки")

    assert runner.submit(work, on_success=lambda _result: None, on_error=errors.append) is False
    assert errors == ["нет калибровки"]


def test_abandon_ignores_the_late_result(qt_app: QApplication) -> None:
    runner = TaskRunner()
    results: list[object] = []
    errors: list[str] = []
    runner.submit(
        lambda: (time.sleep(0.1), "поздний результат")[1],
        on_success=results.append,
        on_error=errors.append,
        label="медленная",
    )
    assert runner.is_busy()
    assert runner.abandon() is True
    assert not runner.is_busy()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert results == []
    assert errors == []
    runner.shutdown()


def test_abandon_without_task_returns_false() -> None:
    assert TaskRunner().abandon() is False
    assert TaskRunner(synchronous=True).abandon() is False


def test_busy_seconds_show_the_wait(qt_app: QApplication) -> None:
    runner = TaskRunner()
    assert runner.busy_seconds() == 0.0
    runner.submit(
        lambda: time.sleep(0.15),
        on_success=lambda _result: None,
        on_error=lambda _message: None,
    )
    time.sleep(0.05)
    assert runner.busy_seconds() >= 0.05
    assert wait_for(qt_app, lambda: not runner.is_busy())
    assert runner.busy_seconds() == 0.0
    runner.shutdown()


def test_handler_error_is_logged_and_does_not_wedge(qt_app: QApplication, caplog) -> None:
    runner = TaskRunner()

    def broken(_result: object) -> None:
        raise RuntimeError("обработчик сломан")

    runner.submit(lambda: 1, on_success=broken, on_error=lambda _m: None)
    assert wait_for(qt_app, lambda: not runner.is_busy())
    assert any(
        record.exc_info is not None and "обработчик сломан" in str(record.exc_info[1])
        for record in caplog.records
    )
    runner.shutdown()


def test_second_task_waits_for_the_abandoned_worker(qt_app: QApplication) -> None:
    """Брошенный поток не даёт запустить второй: иначе два потока кликали бы разом."""
    runner = TaskRunner()
    release = threading.Event()

    def slow() -> object:
        release.wait(2.0)
        return 1

    results: list[object] = []
    runner.submit(slow, on_success=results.append, on_error=lambda _message: None)
    assert wait_for(qt_app, runner.is_worker_alive)
    assert runner.abandon()
    errors: list[str] = []
    assert (
        runner.submit(lambda: 2, on_success=lambda _result: None, on_error=errors.append) is False
    )
    assert errors and "ещё завершается" in errors[0]
    release.set()
    assert wait_for(qt_app, lambda: not runner.is_worker_alive())
    started: list[object] = []
    assert (
        runner.submit(lambda: 3, on_success=started.append, on_error=lambda _message: None) is True
    )
    assert wait_for(qt_app, lambda: started == [3])
