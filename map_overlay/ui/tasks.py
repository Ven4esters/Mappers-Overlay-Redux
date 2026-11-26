"""Фоновые задачи: обмен с панелью идёт в отдельном потоке, окно не замирает."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

from map_overlay.errors import AppError, ApplicationError
from map_overlay.trace import note

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
    """Работа, которую можно положить в ``QThread``.

    Номер задачи едет вместе с сигналом: слот-получатель живёт в потоке интерфейса,
    поэтому результат приходит в него очередью (а не из рабочего потока).
    """

    succeeded = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, work: Work, generation: int) -> None:
        super().__init__()
        self._work = work
        self._generation = generation

    def run(self) -> None:
        """Выполнить работу и сообщить результат сигналом."""
        note("рабочий поток: задача %d начата", self._generation)
        try:
            result = execute(self._work)
        except AppError as exc:
            self.failed.emit(self._generation, str(exc))
        else:
            self.succeeded.emit(self._generation, result)
        finally:
            self._stop_own_thread()
            self.deleteLater()

    def _stop_own_thread(self) -> None:
        """Остановить цикл событий своего потока, не дожидаясь интерфейса."""
        try:
            thread = self.thread()
        except RuntimeError:  # поток уже удалён
            return
        if thread is not None:
            thread.quit()


class TaskRunner(QObject):
    """Запускает задачи по одной: либо в потоке, либо синхронно (для тестов).

    Задача нумеруется: если её бросили (:meth:`abandon`), поздний результат уже не
    попадёт в интерфейс. Ошибка внутри обработчика результата логируется и не мешает
    работе: иначе одно исключение оставило бы окно «занятым» навсегда.
    """

    def __init__(self, *, synchronous: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._synchronous = synchronous
        self._generation = 0
        self._thread: QThread | None = None
        self._tasks: dict[int, _Task] = {}
        self._threads: dict[int, QThread] = {}
        self._active: QThread | None = None
        self._active_generation: int | None = None
        self._label = ""
        self._started_at = 0.0
        self._on_success: SuccessHandler | None = None
        self._on_error: ErrorHandler | None = None

    def is_busy(self) -> bool:
        """Идёт ли сейчас задача."""
        return self._active is not None

    def is_worker_alive(self) -> bool:
        """Работает ли ещё поток брошенной задачи.

        Брошенный поток нельзя убить, поэтому запускать поверх него вторую задачу
        нельзя: два потока начали бы одновременно кликать по панели.
        """
        alive = False
        for generation, thread in list(self._threads.items()):
            try:
                running = thread.isRunning()
            except RuntimeError:  # Qt уже удалил поток
                running = False
            if running:
                alive = True
            else:
                self._threads.pop(generation, None)
        return alive

    def busy_seconds(self) -> float:
        """Сколько секунд выполняется текущая задача."""
        if self._active is None:
            return 0.0
        return time.monotonic() - self._started_at

    def submit(
        self,
        work: Work,
        *,
        on_success: SuccessHandler,
        on_error: ErrorHandler,
        label: str = "задача",
    ) -> bool:
        """Запустить работу.

        Args:
            work: что выполнить в фоне.
            on_success: обработчик результата.
            on_error: обработчик текста ошибки.
            label: название для журнала и строки состояния.

        Returns:
            ``True``, если задача запущена (или уже выполнена синхронно).
        """
        if self.is_busy():
            on_error("Дождитесь окончания предыдущего действия")
            return False
        if self.is_worker_alive():
            on_error(
                "Прошлое действие ещё завершается — повторите через секунду. "
                "Клавиатура уже свободна"
            )
            return False
        self._on_success = on_success
        self._on_error = on_error
        self._label = label
        self._started_at = time.monotonic()
        note(
            "задача «%s» ставится (%s)",
            label,
            "в этом же потоке" if self._synchronous else "в фоне",
        )
        if self._synchronous:
            return self._run_inline(work)
        self._generation += 1
        thread = self._spawn(work, self._generation)
        self._thread = thread
        self._active = thread
        self._active_generation = self._generation
        thread.start()
        logger.info("Задача «%s» начата", label)
        note("задача «%s» начата, поток запущен", label)
        return True

    def _spawn(self, work: Work, generation: int) -> QThread:
        """Создать поток с задачей и связать её сигналы с обработчиками."""
        task = _Task(work, generation)
        thread = QThread(self)
        self._tasks[generation] = task
        self._threads[generation] = thread
        task.moveToThread(thread)
        thread.started.connect(task.run)
        task.succeeded.connect(self._handle_success)
        task.failed.connect(self._handle_failure)
        task.succeeded.connect(thread.quit)
        task.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        return thread

    def abandon(self) -> bool:
        """Бросить текущую задачу: её результат больше не нужен.

        Поток доработает сам (Python-поток нельзя убить безопасно), но всё, что он
        вернёт, будет проигнорировано, а окно снова станет доступным.
        """
        if self._synchronous or self._active is None:
            return False
        logger.warning("Задача «%s» брошена вручную после %.1f с", self._label, self.busy_seconds())
        note(
            "задача «%s» брошена через %.2f с: её результат больше не нужен",
            self._label,
            self.busy_seconds(),
        )
        self._generation += 1
        self._active = None
        self._thread = None
        self._active_generation = None
        return True

    def __del__(self) -> None:
        """Не дать Qt уничтожить поток, пока задача выполняется."""
        with contextlib.suppress(RuntimeError):  # Qt может быть уже разрушен при выходе
            self.shutdown(1000)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Дождаться завершения всех задач при закрытии окна."""
        for thread in list(self._threads.values()):
            try:
                thread.quit()
                if not thread.wait(timeout_ms):
                    logger.warning("Поток задачи не завершился за %d мс", timeout_ms)
            except RuntimeError:  # Qt уже удалил поток после завершения задачи
                continue
        self._threads.clear()
        self._thread = None

    def _run_inline(self, work: Work) -> bool:
        start = time.monotonic()
        try:
            result = execute(work)
        except AppError as exc:
            logger.warning(
                "Задача «%s» не выполнена за %.2f с: %s", self._label, time.monotonic() - start, exc
            )
            note(
                "задача «%s» провалилась за %.2f с: %s", self._label, time.monotonic() - start, exc
            )
            self._call_error(str(exc))
            return False
        logger.info("Задача «%s» выполнена за %.2f с", self._label, time.monotonic() - start)
        note("задача «%s» выполнена за %.2f с", self._label, time.monotonic() - start)
        self._call_success(result)
        return True

    def _handle_success(self, generation: int, result: object) -> None:
        self._tasks.pop(generation, None)
        self._forget(generation)
        if generation != self._generation:
            logger.info("Результат брошенной задачи проигнорирован")
            note("брошенная задача всё-таки завершилась — результат отброшен")
            return
        logger.info("Задача «%s» выполнена за %.2f с", self._label, self.busy_seconds())
        note("задача «%s» выполнена за %.2f с", self._label, self.busy_seconds())
        self._call_success(result)

    def _handle_failure(self, generation: int, message: str) -> None:
        self._tasks.pop(generation, None)
        self._forget(generation)
        if generation != self._generation:
            logger.info("Ошибка брошенной задачи проигнорирована: %s", message)
            note("брошенная задача завершилась ошибкой (отброшена): %s", message)
            return
        logger.warning(
            "Задача «%s» не выполнена за %.2f с: %s", self._label, self.busy_seconds(), message
        )
        note("задача «%s» провалилась за %.2f с: %s", self._label, self.busy_seconds(), message)
        self._call_error(message)

    def _call_success(self, result: object) -> None:
        if self._on_success is None:
            return
        try:
            self._on_success(result)
        except Exception:
            logger.exception("Ошибка в обработчике результата задачи «%s»", self._label)

    def _call_error(self, message: str) -> None:
        if self._on_error is None:
            return
        try:
            self._on_error(message)
        except Exception:
            logger.exception("Ошибка в обработчике ошибки задачи «%s»", self._label)

    def _forget(self, generation: int) -> None:
        """Снять признак занятости, если завершилась именно показанная задача."""
        if generation != self._active_generation:
            return
        self._active = None
        self._thread = None
        self._active_generation = None
