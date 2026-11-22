"""Главное окно оверлея: шапка с командами, вкладки и строка состояния."""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.application.live import LiveMover
from lsp_overlay.application.ports import KeyHookPort, KeyStatePort
from lsp_overlay.application.session import MappingSession
from lsp_overlay.config import Calibration, Settings
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.errors import DomainError
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.pose import Axis, Pose
from lsp_overlay.infrastructure.config_store import ConfigStore
from lsp_overlay.infrastructure.global_keys import NullKeyHook
from lsp_overlay.ui.keymap import (
    NUMPAD_HINT,
    NUMPAD_VK,
    NumpadAction,
    NumpadIntent,
    held_direction,
    numpad_action,
)
from lsp_overlay.ui.styles import STYLESHEET
from lsp_overlay.ui.tabs.calibration_tab import CalibrationTab
from lsp_overlay.ui.tabs.movement_tab import MovementTab
from lsp_overlay.ui.tabs.rotate_tab import RotateTab
from lsp_overlay.ui.tabs.settings_tab import SettingsTab
from lsp_overlay.ui.widgets import make_button

LOGGER = logging.getLogger(__name__)
WINDOW_TITLE = "LSP Mapper Overlay 2.0"
MINIMUM_WIDTH = 380
MINIMUM_HEIGHT = 320
HALF = 0.5
DOUBLE = 2.0
REPEAT_INTERVAL_MS = 90
REPEAT_TIMEOUT_S = 0.6
LIVE_POLL_MS = 250
KEYS_POLL_MS = 60
FLASH_MS = 120
MAX_LIVE_STEPS = 300


class OverlayWindow(QWidget):
    """Окно поверх игры: считает координаты, двигает проп и сохраняет изменения."""

    def __init__(
        self,
        session: MappingSession,
        config_store: ConfigStore,
        settings: Settings,
        *,
        key_state: KeyStatePort | None = None,
        key_hook: KeyHookPort | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._store = config_store
        self._settings = settings
        self._key_state = key_state
        self._key_hook: KeyHookPort = key_hook or NullKeyHook()
        self._hooked_direction: Direction | None = None
        self._hooked_vk: int | None = None
        self._last_key_time = 0.0
        self._repeat_direction: Direction | None = None
        self._live = LiveMover(
            session,
            commit=settings.live_commit,
            hold_timeout=settings.live_hold_timeout,
        )
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(MINIMUM_WIDTH, MINIMUM_HEIGHT)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setInterval(REPEAT_INTERVAL_MS)
        self._repeat_timer.timeout.connect(self._repeat_tick)
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(LIVE_POLL_MS)
        self._live_timer.timeout.connect(self._poll_live)
        self._keys_timer = QTimer(self)
        self._keys_timer.setInterval(KEYS_POLL_MS)
        self._keys_timer.timeout.connect(self._poll_keys)
        self._apply_window_options()
        self._refresh()

    # ------------------------------------------------------------------ сборка
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        root.addLayout(self._build_header())
        self.tabs = QTabWidget()
        self.movement_tab = MovementTab(self._settings)
        self.rotate_tab = RotateTab()
        self.calibration_tab = CalibrationTab(self._settings.calibration)
        self.settings_tab = SettingsTab(self._settings)
        self.tabs.addTab(self.movement_tab, "Движение")
        self.tabs.addTab(self.rotate_tab, "Повороты")
        self.tabs.addTab(self.calibration_tab, "Калибровка")
        self.tabs.addTab(self.settings_tab, "Настройки")
        root.addWidget(self.tabs, 1)
        self.lbl_status = QLabel("Готов. Задайте точки в «Калибровке» и нажмите «Считать из игры».")
        self.lbl_status.setObjectName("statusLabel")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setToolTip(NUMPAD_HINT)
        root.addWidget(self.lbl_status)
        self._connect_tabs()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_capture = make_button(
            "Считать",
            "Прочитать X/Y/Z и RX/RY/RZ из панели игры (Ctrl+A → Ctrl+C)",
            object_name="primaryButton",
        )
        self.btn_apply = make_button("Применить", "Вставить изменённые поля без подтверждения")
        confirm_title = self._settings.confirm_key.upper()
        self.btn_apply_commit = make_button(
            f"Сохранить {confirm_title}",
            "Вставить изменения, кликнуть в пустое место панели и нажать клавишу подтверждения",
            object_name="successButton",
        )
        for button in (self.btn_capture, self.btn_apply, self.btn_apply_commit):
            row.addWidget(button, 1)
        self.btn_mini = make_button("▾", "Свернуть в полоску", object_name="stepButton")
        row.addWidget(self.btn_mini)
        self.btn_capture.clicked.connect(self.action_capture)
        self.btn_apply.clicked.connect(lambda: self.action_apply(commit=False))
        self.btn_apply_commit.clicked.connect(lambda: self.action_apply(commit=True))
        self.btn_mini.clicked.connect(self._toggle_mini)
        return row

    def _connect_tabs(self) -> None:
        self.movement_tab.move_requested.connect(self.action_move)
        self.movement_tab.step_changed.connect(self.action_step_changed)
        self.movement_tab.field_edited.connect(self.action_field_edited)
        self.movement_tab.live_toggled.connect(self.action_live_toggled)
        self.movement_tab.delete_clone_requested.connect(self.action_delete_clone)
        self.rotate_tab.rotate_requested.connect(self.action_rotate)
        self.rotate_tab.angle_set_requested.connect(self.action_set_angle)
        self.calibration_tab.calibration_changed.connect(self.action_calibration_changed)
        self.calibration_tab.status_message.connect(self._set_status)
        self.settings_tab.settings_saved.connect(self.action_settings_saved)
        self.settings_tab.status_message.connect(self._set_status)

    # --------------------------------------------------------------- numpad
    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - переопределение Qt
        """Фокус ушёл (макрос кликнул в игре) — отпускание клавиши мы уже не увидим."""
        self._stop_repeat()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - переопределение Qt
        """Numpad: движение и быстрые команды (стрелки заняты игрой)."""
        action = numpad_action(event.key(), event.modifiers())
        if action is None:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat() and action.intent is NumpadIntent.MOVE:
            # повторяет наш собственный таймер: системный автоповтор только мешает
            event.accept()
            return
        self._run_numpad(action)
        if action.intent is NumpadIntent.MOVE and action.direction is not None:
            self._start_repeat(action.direction)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - переопределение Qt
        """Отпускание Numpad останавливает движение."""
        action = numpad_action(event.key(), event.modifiers())
        if action is None or event.isAutoRepeat():
            super().keyReleaseEvent(event)
            return
        self._stop_repeat()
        event.accept()

    def _start_repeat(self, direction: Direction) -> None:
        self._repeat_direction = direction
        self._last_key_time = time.monotonic()
        if not self._repeat_timer.isActive():
            self._repeat_timer.start()

    def _stop_repeat(self) -> None:
        self._repeat_timer.stop()
        self._repeat_direction = None
        self._live.release()
        self.movement_tab.unflash_all()

    def _repeat_tick(self) -> None:
        """Шаг автоповтора, пока клавиша зажата."""
        direction = self._repeat_direction
        if direction is None:
            self._stop_repeat()
            return
        if time.monotonic() - self._last_key_time > REPEAT_TIMEOUT_S:
            # отпускание могло не дойти: окно потеряло фокус, пока макрос кликал в игре
            LOGGER.warning("Автоповтор остановлен: клавиша давно не нажималась")
            self._stop_repeat()
            return
        self._run_numpad(NumpadAction(intent=NumpadIntent.MOVE, direction=direction))

    def _run_numpad(self, action: NumpadAction) -> None:
        if action.intent is NumpadIntent.MOVE and action.direction is not None:
            self.action_move(action.direction.value, self.movement_tab.current_step())
        elif action.intent is NumpadIntent.CAPTURE:
            self._flash(self.btn_capture)
            self.action_capture()
        elif action.intent is NumpadIntent.COMMIT:
            self._flash(self.btn_apply_commit)
            self.action_apply(commit=True)
        elif action.intent is NumpadIntent.APPLY:
            self._flash(self.btn_apply)
            self.action_apply(commit=False)
        elif action.intent is NumpadIntent.STEP_UP:
            self.movement_tab.scale_step(DOUBLE)
        elif action.intent is NumpadIntent.STEP_DOWN:
            self.movement_tab.scale_step(HALF)

    def _flash(self, button: QPushButton) -> None:
        """Подсвечивает кнопку на мгновение — видно, что команда пришла с клавиатуры."""
        button.setDown(True)
        QTimer.singleShot(FLASH_MS, lambda: button.setDown(False))

    # ----------------------------------------------------------------- действия
    def action_capture(self) -> None:
        """Читает реальные координаты пропа."""
        try:
            pose = self._session.capture()
        except DomainError as error:
            self._fail(error)
            return
        self._set_status(f"Считано: {describe_pose(pose)}", "success")
        self._refresh()

    def action_move(self, direction: str, step: float) -> None:
        """Сдвигает проп: в живом режиме — сразу в игре, иначе только в оверлее."""
        target = Direction(direction)
        self.movement_tab.flash_direction(target)
        if self._live.is_running:
            # кнопка мыши — это один шаг, а не зажатая клавиша: иначе объект поедет
            # бесконечно, ведь отпускания у кнопки нет
            self._live.step_once(target, step)
            return
        before = self._session.pose
        try:
            after = self._session.move(target, step)
        except DomainError as error:
            self._fail(error)
            return
        self._refresh()
        self._set_status(self._move_report(step, before, after), "info")

    def _move_report(self, step: float, before: Pose, after: Pose) -> str:
        """Показывает, что именно произошло: сколько прибавилось по каждой оси."""
        return (
            f"шаг {step:g} м: ΔX {after.x - before.x:+.3f} · ΔY {after.y - before.y:+.3f} · "
            f"ΔZ {after.z - before.z:+.3f} → X {after.x:.3f} · Y {after.y:.3f}"
        )

    def action_live_toggled(self, enabled: bool) -> None:
        """Включает и выключает живой режим с копией объекта."""
        if enabled:
            self._start_live()
        else:
            self._stop_live()

    def _start_live(self) -> None:
        try:
            self._session.clone_object()
            self._session.capture()
        except DomainError as error:
            self.movement_tab.set_live(False)
            self._fail(error)
            return
        self._live.set_commit(self._settings.live_commit)
        self._live.set_hold_timeout(self._settings.live_hold_timeout)
        self._live.start()
        self._live_timer.start()
        if self._key_hook.is_available() and self._key_hook.start(self._on_hooked_key):
            LOGGER.info("Живой режим: Numpad перехватывается хуком")
        elif self._global_keys_ready():
            LOGGER.warning("Хук недоступен: клавиши читаются опросом, игра их тоже видит")
            self._keys_timer.start()
        else:
            LOGGER.warning("Живой режим без глобальных клавиш: двигайте кнопками оверлея")
        self.movement_tab.set_live(True)
        self._refresh()
        hint = (
            "каждый шаг подтверждается F"
            if self._settings.live_commit
            else "F не нажимается: видно, куда встанет предмет"
        )
        numpad = "" if self._num_lock_ok() else " NumLock выключен — Numpad шлёт другие клавиши."
        self._set_status(f"Живой режим: двигайте копию Numpad — {hint}.{numpad}", "success")

    def _stop_live(self) -> None:
        self._key_hook.stop()
        self._live.stop()
        self._live_timer.stop()
        self._keys_timer.stop()
        self._hooked_direction = None
        self._hooked_vk = None
        self.movement_tab.unflash_all()
        self.movement_tab.set_live(False)
        self._refresh()
        tail = "с подтверждением F" if self._settings.live_commit else "без подтверждения F"
        self._set_status(
            f"Живой режим выключен, шагов: {self._live.applied} ({tail})",
            "info",
        )

    def action_delete_clone(self) -> None:
        """Удаляет копию по явной команде."""
        try:
            self._session.delete_clone()
        except DomainError as error:
            self._fail(error)
            return
        self._set_status("Копия удалена", "info")

    def _on_hooked_key(self, vk_code: int, pressed: bool) -> None:
        """Событие перехваченной клавиши Numpad: игра её уже не увидит."""
        if not self._live.is_running:
            return
        direction = NUMPAD_VK.get(vk_code)
        if direction is None:
            return
        if pressed:
            self._hooked_direction = direction
            self._hooked_vk = vk_code
            self.movement_tab.flash_direction(direction)
            self._live.steer(direction, self.movement_tab.current_step())
            return
        if self._hooked_direction is direction:
            self._hooked_direction = None
            self._hooked_vk = None
            self._live.release()
        self.movement_tab.unflash_direction(direction)

    def _global_keys_ready(self) -> bool:
        return self._key_state is not None and self._key_state.is_ready()

    def _num_lock_ok(self) -> bool:
        state = self._key_state
        return state is None or not state.is_ready() or state.num_lock_enabled()

    def _poll_keys(self) -> None:
        """Читает зажатые клавиши Numpad напрямую у Windows: фокус может быть в игре."""
        state = self._key_state
        if state is None or not self._live.is_running:
            return
        direction = held_direction(state.is_down)
        if direction is None:
            if self._live.direction is not None:
                self._live.release()
                self.movement_tab.unflash_all()
            return
        self.movement_tab.flash_direction(direction)
        self._live.steer(direction, self.movement_tab.current_step())

    def _confirm_key_still_held(self) -> None:
        """Сверяет удержание с реальным состоянием клавиши: отпускание могло потеряться."""
        vk_code = self._hooked_vk
        direction = self._hooked_direction
        if vk_code is None or direction is None:
            return
        state = self._key_state
        if state is None or not state.is_ready():
            return
        if state.is_down(vk_code):
            # клавиша действительно зажата — продлеваем удержание, даже если автоповтор
            # сработал не сразу или событие потерялось
            self._live.steer(direction, self.movement_tab.current_step())
            return
        LOGGER.info("Клавиша отпущена, но событие потерялось — движение остановлено")
        self._hooked_direction = None
        self._hooked_vk = None
        self._live.release()
        self.movement_tab.unflash_all()

    def _guard_live(self) -> bool:
        """Останавливает живой режим, если шагов стало слишком много подряд."""
        if self._live.applied < MAX_LIVE_STEPS:
            return False
        self._key_hook.stop()
        self._live.stop()
        self._live_timer.stop()
        self._keys_timer.stop()
        self.movement_tab.set_live(False)
        self._set_status(
            f"Живой режим остановлен предохранителем: {self._live.applied} шагов подряд",
            "error",
        )
        return True

    def _poll_live(self) -> None:
        """Показывает, что делает поток живого режима, и следит за удержанием клавиши."""
        self._confirm_key_still_held()
        if self._guard_live():
            return
        error = self._live.last_error
        self._refresh()
        if error is not None:
            # снимаем и хук: иначе Numpad остался бы забранным у игры
            self._stop_live()
            self._set_status(f"Живой режим остановлен: {error}", "error")
            return
        if self._live.direction is None:
            self._set_status(f"Живой режим: шагов {self._live.applied}, жду клавишу", "info")

    def action_rotate(self, axis: str, degrees: float) -> None:
        """Поворот на шаг."""
        try:
            self._session.rotate(Axis(axis), degrees)
        except DomainError as error:
            self._fail(error)
            return
        self._refresh()

    def action_set_angle(self, axis: str, degrees: float) -> None:
        """Устанавливает абсолютный угол."""
        try:
            self._session.set_field(FieldKey(axis), degrees)
        except DomainError as error:
            self._fail(error)
            return
        self._refresh()

    def action_field_edited(self, key: str, value: float) -> None:
        """Ручная правка координаты в таблице полей."""
        try:
            self._session.set_field(FieldKey(key), value)
        except DomainError as error:
            self._fail(error)
            return
        self._refresh()

    def action_step_changed(self, step: float) -> None:
        """Запоминает выбранный шаг."""
        try:
            self._settings = self._settings.with_step(step)
        except (DomainError, ValueError) as error:
            self._fail(error)
            return
        self._session.update_settings(self._settings)
        self._save_settings()
        self._set_status(f"Шаг: {step:g} м", "info")

    def action_settings_saved(self, settings: Settings) -> None:
        """Применяет настройки из вкладки."""
        self._settings = settings
        self._session.update_settings(settings)
        self._apply_calibration_to_panel(settings.calibration)
        self._apply_window_options()
        self._save_settings()
        self._live.set_commit(settings.live_commit)
        self._live.set_hold_timeout(settings.live_hold_timeout)
        self.movement_tab.set_step(settings.step)
        self.btn_apply_commit.setText(f"Сохранить {settings.confirm_key.upper()}")
        self._set_status("Настройки сохранены", "success")

    def action_calibration_changed(self, calibration: Calibration) -> None:
        """Сохраняет новые точки и передаёт их панели."""
        self._settings = _with_calibration(self._settings, calibration)
        self._session.update_settings(self._settings)
        self._apply_calibration_to_panel(calibration)
        self._save_settings()

    def action_apply(self, *, commit: bool) -> None:
        """Пишет изменения в игру."""
        try:
            result = self._session.apply(commit=commit)
        except DomainError as error:
            self._fail(error)
            return
        if not result.fields:
            self._set_status("Изменений нет — нечего записывать", "info")
        else:
            names = ", ".join(key.value.upper() for key in result.fields)
            suffix = " и сохранено (F)" if commit else ""
            self._set_status(f"Записано: {names}{suffix}", "success")
        self._refresh()

    # ------------------------------------------------------------------ сервис
    def _fail(self, error: Exception) -> None:
        LOGGER.warning("Ошибка действия: %s", error)
        self._set_status(str(error), "error")

    def _set_status(self, text: str, level: str = "info") -> None:
        self.lbl_status.setText(text)
        self.lbl_status.setProperty("level", level)
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def _save_settings(self) -> None:
        with contextlib.suppress(OSError):
            self._store.save(self._settings)

    def _apply_calibration_to_panel(self, calibration: Calibration) -> None:
        self._session.configure_panel(
            calibration=calibration,
            timings=self._settings.timings,
            length_decimals=self._settings.length_decimals,
            confirm_key=self._settings.confirm_key,
        )

    def _apply_window_options(self) -> None:
        self.setWindowOpacity(self._settings.overlay_opacity)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._settings.always_on_top)
        self.show()

    def _toggle_mini(self) -> None:
        collapsed = self.tabs.isHidden()
        self.tabs.setVisible(collapsed)
        self.btn_mini.setText("▾" if collapsed else "▴")
        self.adjustSize()

    def _refresh(self) -> None:
        self.movement_tab.update_pose(self._session.pose, self._session.pending_fields())
        pending = len(self._session.pending_fields())
        self.btn_apply.setEnabled(pending > 0)
        self.btn_apply_commit.setEnabled(pending > 0)
        self.movement_tab.set_live(self._live.is_running)

    def closeEvent(self, event: object) -> None:  # noqa: N802 - переопределение Qt
        """Закрытие окна снимает хук и останавливает поток живого режима."""
        self._key_hook.stop()
        self._live.stop()
        super().closeEvent(event)  # type: ignore[arg-type]


def _with_calibration(settings: Settings, calibration: Calibration) -> Settings:
    return replace(settings, calibration=calibration)


def describe_pose(pose: Pose) -> str:
    """Короткое описание позы для строки состояния и логов."""
    return (
        f"X={pose.x:.2f} Y={pose.y:.2f} Z={pose.z:.2f} "
        f"RX={pose.rx:.2f}° RY={pose.ry:.2f}° RZ={pose.rz:.2f}°"
    )
