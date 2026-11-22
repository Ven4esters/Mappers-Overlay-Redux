"""Фоновые задачи: поток, ошибки и занятость."""

from __future__ import annotations

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
