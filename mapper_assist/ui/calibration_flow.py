from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..logger import get_logger
from ..models import CALIBRATION_LABELS, CALIBRATION_TARGETS


logger = get_logger("mapper_assist.ui.calibration")


class CalibrationFlow(QObject):
    """
    Пошаговая калибровка экранных точек панели LSP.
    Отвечает за очередь точек, живой баннер с текущими координатами курсора,
    захват по горячей клавише и резервный захват по таймеру (3 секунды).
    """

    banner_text_changed = Signal(str)
    point_captured = Signal(str, int, int)  # target, x, y
    finished = Signal()
    cancelled = Signal()
    active_changed = Signal(bool)

    def __init__(
        self,
        cursor_provider: Callable[[], tuple[int, int]],
        hotkey_name_provider: Callable[[], str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cursor_provider = cursor_provider
        self._hotkey_name_provider = hotkey_name_provider
        self._queue: list[str] = []
        self._countdown_remaining = 0

        self._banner_timer = QTimer(self)
        self._banner_timer.setInterval(80)
        self._banner_timer.timeout.connect(self._refresh_banner)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

    # ------------------------------------------------------------------ state
    @property
    def is_active(self) -> bool:
        return bool(self._queue)

    @property
    def remaining(self) -> int:
        return len(self._queue)

    @property
    def current_target(self) -> str | None:
        return self._queue[0] if self._queue else None

    # ------------------------------------------------------------------ commands
    def start_full(self) -> None:
        self._start(list(CALIBRATION_TARGETS))

    def start_single(self, target: str) -> None:
        self._start([target])

    def _start(self, targets: list[str]) -> None:
        self._countdown_timer.stop()
        self._queue = targets
        self._banner_timer.start()
        self.active_changed.emit(True)
        logger.info("Калибровка запущена: %s", ", ".join(targets))
        self._refresh_banner()

    def cancel(self) -> None:
        if not self._queue:
            return
        logger.info("Калибровка отменена пользователем")
        self._queue.clear()
        self._banner_timer.stop()
        self._countdown_timer.stop()
        self.active_changed.emit(False)
        self.cancelled.emit()

    def start_countdown(self, seconds: int = 3) -> None:
        """Резервный захват: пользователь наводит курсор и ждёт, ничего не нажимая."""
        if not self._queue:
            return
        self._countdown_remaining = seconds
        self._countdown_timer.start()
        self._refresh_banner()

    def capture_now(self) -> None:
        if not self._queue:
            return
        target = self._queue.pop(0)
        x, y = self._cursor_provider()
        logger.info("Точка '%s' зафиксирована в (%d, %d)", target, x, y)
        self.point_captured.emit(target, x, y)

        if self._queue:
            self._refresh_banner()
        else:
            self.stop_after_finish()

    def stop_after_finish(self) -> None:
        self._banner_timer.stop()
        self._countdown_timer.stop()
        self.active_changed.emit(False)
        self.finished.emit()

    # ------------------------------------------------------------------ view
    def _refresh_banner(self) -> None:
        if not self._queue:
            return
        target = self._queue[0]
        cx, cy = self._cursor_provider()
        if self._countdown_timer.isActive():
            text = (
                f"Держите курсор на «{CALIBRATION_LABELS[target]}» — фиксация через "
                f"{self._countdown_remaining} сек... [{cx}, {cy}]"
            )
        else:
            text = (
                f"Наведите мышь на «{CALIBRATION_LABELS[target]}» и нажмите "
                f"{self._hotkey_name_provider() or 'F9'} (осталось: {len(self._queue)})\n"
                f"Курсор: X={cx}, Y={cy}"
            )
        self.banner_text_changed.emit(text)

    def _on_countdown_tick(self) -> None:
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._countdown_timer.stop()
            self.capture_now()
        else:
            self._refresh_banner()

    def shutdown(self) -> None:
        self._banner_timer.stop()
        self._countdown_timer.stop()
