"""Горячие клавиши: перехват, обучение, маршрутизация команд.

Сюда приходят события хука, здесь назначаются клавиши, проверяется NumLock и пишется
сводка «жив». Режим высоты и удержание — в части движения: клавиатура только решает,
что нажали, а действует уже сценарий."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from PySide6.QtCore import QEvent

from map_overlay.domain.actions import Action
from map_overlay.domain.keynames import COMMON_GAME_KEYS, VK_ESCAPE, VK_MENU, key_name
from map_overlay.errors import ConfigError
from map_overlay.trace import note
from map_overlay.ui.tabs.movement_tab import pose_text
from map_overlay.ui.window_base import (
    LEARN_TIMEOUT_MS,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_WARN,
    WindowBase,
)

logger = logging.getLogger(__name__)


class WindowHotkeysMixin(WindowBase):
    """Часть окна: см. описание модуля, состояние — в ``WindowBase``."""

    def _on_hotkey(self, vk: int, is_down: bool, fresh: bool = True, ctrl: bool = False) -> None:
        """Событие клавиатуры: сюда приходит даже автоповтор зажатой клавиши.

        ``ctrl`` говорит, была ли нажата клавиша с зажатым Ctrl: от этого зависит,
        наша это клавиша или игра должна получить её как обычную Z/Y.
        """
        note_keyboard_event(vk, is_down, fresh)
        if not self.settings_tab.hotkeys_enabled():
            logger.debug("Клавиша %s: перехват выключен", key_name(vk))
            note("клавиша %s пропущена: перехват выключен", key_name(vk))
            return
        if self._learning is not None:
            if is_down:
                self._finish_learning(vk)
            return
        if vk == VK_MENU and is_down and fresh:
            self._toggle_tilt()
            return
        action = self._router.handle(vk, is_down, fresh, ctrl)
        if action is None:
            if not is_down:
                self._release_key(vk)
            return
        logger.info("Клавиша %s → %s", key_name(vk), action.label)
        note("клавиша %s → команда «%s»", key_name(vk), action.label)
        self._dispatch(action, vk)

    def _dispatch(self, action: Action, vk: int) -> None:
        if action is Action.UNDO:
            self.undo()
            return
        if action is Action.REDO:
            self.redo()
            return
        if action is Action.CAPTURE:
            self._capture()
            return
        if action is Action.PASTE:
            self._paste()
            return
        if action is Action.CONFIRM:
            self._confirm()
            return
        if action.direction is not None:
            if self._hotkeys.key_down(VK_MENU) and not self._tilt_mode:
                # Привычка «Alt + направление» тоже включает режим.
                self._set_tilt(True)
            self._start_hold(action, vk)

    def _start_learning(self, action: object) -> None:
        self._stop_hold()
        if not self.settings_tab.hotkeys_enabled():
            self._set_status("Перехват клавиш выключен — назначить клавишу нельзя.", STATUS_WARN)
            return
        selected = cast(Action, action)
        note("назначение клавиши для «%s»: жду нажатия", selected.label)
        self._learning = selected
        self._hotkeys.configure(bound_keys=self._router.bound_keys, learning=True)
        self._learn_timer.start(LEARN_TIMEOUT_MS)
        self._set_status(f"Нажмите клавишу для «{selected.label}» (Esc — отмена)")

    def _cancel_learning(self, reason: str) -> None:
        """Отменить запись привязки: клавиатура возвращается игре."""
        if self._learning is None:
            return
        self._learning = None
        self._learn_timer.stop()
        self._hotkeys.configure(bound_keys=self._router.bound_keys, learning=False)
        self._set_status(f"Назначение клавиши отменено: {reason}", STATUS_WARN)

    def _learning_expired(self) -> None:
        self._cancel_learning("время вышло")

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - имя из Qt
        """Потеря фокуса отменяет запись привязки: иначе окно «съест» клавиатуру."""
        super().changeEvent(event)
        activation = event.type() == QEvent.Type.ActivationChange
        if activation and not self.isActiveWindow():
            self._cancel_learning("окно потеряло фокус")

    def _set_hotkeys_enabled(self, enabled: bool) -> None:
        """Включить или приостановить перехват клавиш без перезапуска."""
        self._stop_hold()
        self._router.reset()
        self._hotkeys.set_enabled(enabled)
        if enabled:
            self._set_status("Перехват клавиш включён: Numpad снова забран у игры.")
            self._check_num_lock()
        else:
            self._cancel_learning("перехват выключен")
            self._set_status(
                "Перехват выключен: игра получает все клавиши, кнопки работают мышью.",
                STATUS_WARN,
            )

    def _finish_learning(self, vk: int) -> None:
        action = self._learning
        self._learning = None
        self._learn_timer.stop()
        self._hotkeys.configure(bound_keys=self._router.bound_keys, learning=False)
        if action is None:
            return
        if vk == VK_ESCAPE:
            self._set_status("Назначение клавиши отменено")
            return
        try:
            settings = self._context.settings.with_hotkey(action, vk)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        if not self._apply_settings(settings):
            return
        self._set_status(f"Клавиша {key_name(vk)} назначена на «{action.label}»", STATUS_OK)
        if vk in COMMON_GAME_KEYS:
            self._set_status(
                f"Клавиша {key_name(vk)} обычно занята в игре: теперь она достанется "
                f"оверлею, а не игре.",
                STATUS_WARN,
            )

    def _clear_hotkey(self, action: object) -> None:
        selected = cast(Action, action)
        try:
            settings = self._context.settings.with_hotkey(selected, None)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        if not self._apply_settings(settings):
            return
        self._set_status(f"Клавиша для «{selected.label}» снята")

    def _apply_hotkeys(self, hotkeys: Mapping[Action, int | None]) -> None:
        self._router.bind(hotkeys)
        self._router.reset()
        self._hotkeys.configure(
            bound_keys=self._router.bound_keys,
            bound_ctrl_keys=self._router.bound_ctrl_keys,
            learning=self._learning is not None,
        )
        self.settings_tab.set_hotkeys(hotkeys)

    def _log_state(self) -> None:
        """Записать «жив» со сводкой: что происходит прямо сейчас."""
        pose = self._pose
        note(
            "жив: занято=%s%s, шаг=%s, удержание=%s, высота=%s, координаты=%s",
            "да" if self._runner.is_busy() else "нет",
            f" ({self._busy_text}, {self._runner.busy_seconds():.0f} с)"
            if self._runner.is_busy()
            else "",
            self.movement.step_text(),
            self._held[0].label if self._held is not None else "нет",
            "вкл" if self._tilt_mode else "выкл",
            pose_text(pose) if pose is not None else "не считаны",
        )

    def _check_num_lock(self) -> None:
        """Следить за NumLock: без него Numpad посылает «стрелки», а не цифры."""
        state = self._hotkeys.num_lock_enabled()
        if state == self._num_lock_state:
            return
        self._num_lock_state = state
        if state is False:
            warning = (
                "NumLock выключен: цифровой блок работает как навигация, "
                "горячие клавиши не сработают."
            )
            logger.warning("NumLock выключен: Numpad посылает другие клавиши")
            self.settings_tab.set_num_lock_warning(warning)
            self._set_status(warning, STATUS_WARN)
        else:
            self.settings_tab.set_num_lock_warning("")

    def check_hotkey_state(self) -> None:
        """Сообщить, если хук клавиатуры не установился."""
        if not self._hotkeys.is_available():
            self._set_status(
                "Горячие клавиши недоступны: хук клавиатуры не установлен (см. журнал). "
                "Кнопки в окне работают как обычно.",
                STATUS_ERROR,
            )


def note_keyboard_event(vk: int, is_down: bool, fresh: bool) -> None:
    """Строка журнала о каждом событии: по ней видно, дошли ли клавиши до оверлея."""
    repeat = " (автоповтор)" if is_down and not fresh else ""
    note("клавиша %s %s%s", key_name(vk), "нажата" if is_down else "отпущена", repeat)
