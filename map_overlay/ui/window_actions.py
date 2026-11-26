"""Занятость окна: обмен с панелью, дедлайн, «Прервать».

Пока идёт обмен, клавиатура заморожена, а в строке состояния виден счётчик; по дедлайну
обмен прерывается сам, чтобы окно не зависло навсегда."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer

from map_overlay.application.session import MappingSession
from map_overlay.trace import note
from map_overlay.ui.window_base import (
    ACTION_DEADLINE_MS,
    BUSY_TICK_MS,
    STATUS_WARN,
    STUCK_HINT_S,
    UNFREEZE_POLL_MS,
    UNFREEZE_WAIT_MS,
    WindowBase,
)

logger = logging.getLogger(__name__)


class WindowActionsMixin(WindowBase):
    """Часть окна: см. описание модуля, состояние — в ``WindowBase``."""

    def _set_busy(self, busy: bool) -> None:
        """Показать занятость и закрыть клавиатуру на время обмена с панелью.

        Заморозка нужна не для красоты: пока оверлей кликает по полю и посылает
        ``Ctrl+A``/``Ctrl+V``, случайное нажатие (например ``Alt+A``) дописывает в
        поле символ, значение перестаёт читаться, и обмен повторяется впустую.
        """
        self.movement.set_busy(busy)
        self._abort_button.setEnabled(busy)
        note("занятость: %s", "включена" if busy else "снята")
        if busy:
            self._hotkeys.freeze(True)
            self._busy_timer.start(BUSY_TICK_MS)
            self._deadline_timer.start(ACTION_DEADLINE_MS)
        else:
            self._busy_timer.stop()
            self._deadline_timer.stop()
            # Клавиатуру отпускаем только когда брошенный поток действительно вышел:
            # иначе нажатие попадёт в панель между кликом и вставкой. Ожидание ограничено.
            self._unfreeze_when_worker_stops()

    def _unfreeze_when_worker_stops(self, waited_ms: int = 0) -> None:
        """Отпустить клавиатуру, когда рабочий поток закончил (не дольше ``UNFREEZE_WAIT_MS``)."""
        if self._runner.is_worker_alive() and waited_ms < UNFREEZE_WAIT_MS:
            QTimer.singleShot(
                UNFREEZE_POLL_MS,
                lambda: self._unfreeze_when_worker_stops(waited_ms + UNFREEZE_POLL_MS),
            )
            return
        self._hotkeys.freeze(False)

    def _action_deadline(self) -> None:
        """Прервать обмен, который не уложился в отведённое время.

        Так окно не может «зависнуть» навсегда: даже если рабочий поток застрял,
        интерфейс разблокируется, клавиатура размораживается, а причина уходит в журнал.
        """
        if not self._runner.is_busy():
            return
        note(
            "дедлайн: обмен «%s» идёт %.1f с — прерываю",
            self._busy_text,
            self._runner.busy_seconds(),
        )
        logger.warning(
            "Обмен с панелью прерван по таймауту: «%s» шёл %.1f с",
            self._busy_text,
            self._runner.busy_seconds(),
        )
        self._stop_hold()
        self._cancel_running()
        self._set_busy(False)
        self._drop_pose("Панель не ответила за 20 с")
        self._set_status(
            "Действие прервано: панель не ответила за 20 с. Проверьте, что окно панели "
            "на экране и не перекрыто, и нажмите «Считать».",
            STATUS_WARN,
        )

    def _begin_busy(self, text: str) -> None:
        """Показать, что идёт обмен с панелью, и засечь время."""
        note("начато действие: %s", text)
        self._busy_text = text
        self._set_busy(True)
        self._set_status(text)

    def _busy_tick(self) -> None:
        """Обновлять счётчик времени, чтобы «занято» не выглядело как «зависло»."""
        if not self._runner.is_busy():
            self._busy_timer.stop()
            return
        seconds = self._runner.busy_seconds()
        if seconds >= STUCK_HINT_S:
            self._set_status(
                f"{self._busy_text} ({seconds:.0f} с) — панель не отвечает? Нажмите «Прервать».",
                STATUS_WARN,
            )
            return
        self._set_status(f"{self._busy_text} ({seconds:.0f} с)")

    def _cancel_running(self) -> bool:
        """Остановить обмен: сначала попросить рабочий поток выйти, потом бросить задачу.

        Без сигнала отмены брошенный поток продолжал бы кликать и вставлять значения,
        пока не пройдёт все поля: панель получала бы чужие нажатия, а координаты —
        мусор. Отмена видна панели между шагами и завершает поток за один шаг.
        """
        if self._session is not None:
            self._session.cancel()
        return self._runner.abandon()

    def _abort_action(self) -> None:
        """Бросить зависшее действие, не закрывая окно."""
        self._stop_hold()
        note("нажата кнопка «Прервать»")
        if not self._cancel_running():
            note("прерывать нечего: обмена нет")
            return
        self._set_busy(False)
        self._drop_pose("Действие прервано вручную")
        self._set_status(
            "Действие прервано вручную, удержание остановлено. "
            "Клавиатура свободна. Нажмите «Считать», чтобы продолжить.",
            STATUS_WARN,
        )

    def _drop_pose(self, reason: str) -> None:
        """Забыть координаты: после сбоя двигаться от них нельзя."""
        if self._pose is None:
            return
        self._history.clear()
        logger.warning("%s — координаты сброшены, нужен новый «Считать»", reason)
        self._pose = None
        self.movement.set_pose(None)

    def _ensure_session(self) -> MappingSession:
        if self._session is None:
            self._session = self._context.make_session()
        return self._session

    def _check_step_ready(self, what: str) -> bool:
        """Можно ли сейчас ставить шаг (в том числе отмену): не занято и есть координаты."""
        if self._runner.is_busy():
            self._set_status(f"Дождитесь окончания действия: {what} пока нельзя.", STATUS_WARN)
            return False
        if self._session is None or self._session.pose is None or self._pose is None:
            self._set_status(
                f"Сначала нажмите «Считать»: без координат {what} нечего.", STATUS_WARN
            )
            return False
        return True
