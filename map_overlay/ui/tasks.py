"""Фоновые задачи: обмен с панелью идёт в отдельном потоке, окно не замирает."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

from map_overlay.errors import AppError, ApplicationError

logger = logging.getLogger(__name__)

Work = Callable[[], object]
SuccessHandler = Callable[[object], None]
ErrorHandler = Callable[[str], None]


def execute(work: Work) -> object:
    """Выполнить работу, превращая неожиданные ошибки в понятный текст.

    Raises:
        AppError: ожидаемая ошибка приложения.
        ApplicationError: обёртка неожиданного исключения.
    """
    try:
        return work()
    except AppError:
        raise
    except Exception as exc:
        logger.exception("Неожиданная ошибка в фоновой задаче")
        raise ApplicationError(f"Внутренняя ошибка: {exc}") from exc


class _Task(QObject):
    """Работа, которую можно положить в ``QThread``."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Work) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        """Выполнить работу и сообщить результат сигналом."""
        try:
            result = execute(self._work)
        except AppError as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)
        finally:
            self.deleteLater()


class TaskRunner(QObject):
    """Запускает задачи по одной: либо в потоке, либо синхронно (для тестов)."""

    def __init__(self, *, synchronous: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._synchronous = synchronous
        self._thread: QThread | None = None
        self._task: _Task | None = None
        self._on_success: SuccessHandler | None = None
        self._on_error: ErrorHandler | None = None

    def is_busy(self) -> bool:
        """Идёт ли сейчас задача."""
        return self._thread is not None

    def submit(self, work: Work, *, on_success: SuccessHandler, on_error: ErrorHandler) -> bool:
        """Запустить работу.

        Returns:
            ``True``, если задача запущена (или уже выполнена синхронно).
        """
        if self.is_busy():
            on_error("Дождитесь окончания предыдущего действия")
            return False
        if self._synchronous:
            try:
                result = execute(work)
            except AppError as exc:
                on_error(str(exc))
                return False
            on_success(result)
            return True
        self._on_success = on_success
        self._on_error = on_error
        task = _Task(work)
        thread = QThread(self)
        task.moveToThread(thread)
        thread.started.connect(task.run)
        task.succeeded.connect(self._handle_success)
        task.failed.connect(self._handle_failure)
        task.succeeded.connect(thread.quit)
        task.failed.connect(thread.quit)
        thread.finished.connect(self._release)
        self._task = task
        self._thread = thread
        thread.start()
        return True

    def __del__(self) -> None:
        """Не дать Qt уничтожить поток, пока задача выполняется."""
        with contextlib.suppress(RuntimeError):  # Qt может быть уже разрушен при выходе
            self.shutdown(1000)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Дождаться завершения задачи при закрытии окна."""
        thread = self._thread
        if thread is None:
            return
        thread.quit()
        if not thread.wait(timeout_ms):
            logger.warning("Поток задачи не завершился за %d мс", timeout_ms)

    def _handle_success(self, result: object) -> None:
        if self._on_success is not None:
            self._on_success(result)

    def _handle_failure(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)

    def _release(self) -> None:
        thread = self._thread
        self._thread = None
        self._task = None
        if thread is not None:
            thread.deleteLater()
