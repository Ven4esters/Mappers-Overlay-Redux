from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal

from ..logger import get_logger


logger = get_logger("mapper_assist.ui.threads")


class HotkeyBridge(QObject):
    """Потокобезопасный мост: колбэк из Win32-потока хоткеев -> сигнал в GUI-поток Qt."""

    triggered = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def emit_action(self, action_id: str) -> None:
        self.triggered.emit(action_id)


class MacroRunner(QObject):
    """
    Асинхронный исполнитель макросов панели LSP.
    Работает в отдельном потоке, не блокирует интерфейс, гарантирует
    «ровно одну одновременно выполняемую операцию» и передаёт результаты в GUI-поток сигналами.
    """

    finished = Signal(str, object)  # (сообщение для пользователя, полезная нагрузка)
    failed = Signal(str)            # текст ошибки
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._busy = False

    @property
    def is_busy(self) -> bool:
        return self._busy

    def run(self, task_fn: Callable[[], tuple[str, object]], label: str = "макрос") -> bool:
        with self._lock:
            if self._busy:
                logger.warning("Пропуск '%s': предыдущий макрос ещё выполняется", label)
                return False
            self._busy = True
        self.busy_changed.emit(True)
        logger.debug("Запуск фонового макроса '%s'", label)

        def _worker() -> None:
            try:
                msg, payload = task_fn()
                logger.debug("Макрос '%s' успешно завершён: %s", label, msg)
                self.finished.emit(msg, payload)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ошибка выполнения макроса '%s'", label)
                self.failed.emit(str(exc))
            finally:
                with self._lock:
                    self._busy = False
                self.busy_changed.emit(False)

        thread = threading.Thread(target=_worker, name=f"LSPMacro-{label}", daemon=True)
        thread.start()
        return True
