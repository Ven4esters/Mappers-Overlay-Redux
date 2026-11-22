"""Главное окно оверлея: шапка с командами, вкладки и строка состояния."""

from __future__ import annotations

import contextlib
import logging
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.application.session import MappingSession
from lsp_overlay.config import Calibration, Settings
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.errors import DomainError
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.formatting import format_length
from lsp_overlay.domain.measure import MeasureSlot
from lsp_overlay.domain.pose import Axis, Pose
from lsp_overlay.infrastructure.config_store import ConfigStore
from lsp_overlay.ui.keymap import NumpadAction, NumpadIntent, numpad_action
from lsp_overlay.ui.styles import STYLESHEET
from lsp_overlay.ui.tabs.calibration_tab import CalibrationTab
from lsp_overlay.ui.tabs.measure_tab import MeasureTab
from lsp_overlay.ui.tabs.movement_tab import STEP_MAX, STEP_MIN, MovementTab
from lsp_overlay.ui.tabs.rotate_tab import RotateTab
from lsp_overlay.ui.tabs.settings_tab import SettingsTab
from lsp_overlay.ui.widgets import make_button

LOGGER = logging.getLogger(__name__)
WINDOW_TITLE = "LSP Mapper Overlay 2.0"
MINIMUM_WIDTH = 380
MINIMUM_HEIGHT = 320
HALF = 0.5
DOUBLE = 2.0


class OverlayWindow(QWidget):
    """Окно поверх игры: считает координаты, двигает проп и сохраняет изменения."""

    def __init__(
        self,
        session: MappingSession,
        config_store: ConfigStore,
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._store = config_store
        self._settings = settings
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(MINIMUM_WIDTH, MINIMUM_HEIGHT)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()
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
        self.measure_tab = MeasureTab()
        self.calibration_tab = CalibrationTab(self._settings.calibration)
        self.settings_tab = SettingsTab(self._settings)
        self.tabs.addTab(self.movement_tab, "Движение")
        self.tabs.addTab(self.rotate_tab, "Повороты")
        self.tabs.addTab(self.measure_tab, "Рулетка")
        self.tabs.addTab(self.calibration_tab, "Калибровка")
        self.tabs.addTab(self.settings_tab, "Настройки")
        root.addWidget(self.tabs, 1)
        self.lbl_status = QLabel("Готов. Задайте точки в «Калибровке» и нажмите «Считать из игры».")
        self.lbl_status.setObjectName("statusLabel")
        self.lbl_status.setWordWrap(True)
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
        self.rotate_tab.rotate_requested.connect(self.action_rotate)
        self.rotate_tab.angle_set_requested.connect(self.action_set_angle)
        self.measure_tab.remember_requested.connect(self.action_remember_point)
        self.measure_tab.reset_requested.connect(self.action_clear_tape)
        self.measure_tab.step_requested.connect(self.action_measure_step)
        self.measure_tab.status_message.connect(self._set_status)
        self.calibration_tab.calibration_changed.connect(self.action_calibration_changed)
        self.calibration_tab.status_message.connect(self._set_status)
        self.calibration_tab.diagnostics_requested.connect(self.action_diagnostics)
        self.settings_tab.settings_saved.connect(self.action_settings_saved)
        self.settings_tab.status_message.connect(self._set_status)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - переопределение Qt
        """Numpad: движение и быстрые команды (стрелки заняты игрой)."""
        action = numpad_action(event.key(), event.modifiers())
        if action is None:
            super().keyPressEvent(event)
            return
        self._run_numpad(action)
        event.accept()

    def _run_numpad(self, action: NumpadAction) -> None:
        if action.intent is NumpadIntent.MOVE and action.direction is not None:
            self.action_move(action.direction.value, self.movement_tab.current_step())
        elif action.intent is NumpadIntent.CAPTURE:
            self.action_capture()
        elif action.intent is NumpadIntent.COMMIT:
            self.action_apply(commit=True)
        elif action.intent is NumpadIntent.APPLY:
            self.action_apply(commit=False)
        elif action.intent is NumpadIntent.STEP_UP:
            self.movement_tab.scale_step(DOUBLE)
        elif action.intent is NumpadIntent.STEP_DOWN:
            self.movement_tab.scale_step(HALF)

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
        """Сдвигает проп в локальном направлении."""
        try:
            self._session.move(Direction(direction), step)
        except DomainError as error:
            self._fail(error)
            return
        self._refresh()

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

    def action_remember_point(self, slot: str) -> None:
        """Запоминает текущее положение пропа как точку рулетки."""
        span = self._session.remember_point(MeasureSlot(slot))
        point = MeasureSlot(slot)
        if span is None:
            self._set_status(f"Точка {point.label} запомнена — поставьте проп у другого края")
        else:
            self._set_status(
                f"Длина: {format_length(span.length_for_step(), 3)} м "
                f"(по прямой {format_length(span.distance, 3)} м)",
                "success",
            )
        self._refresh()

    def action_clear_tape(self) -> None:
        """Сбрасывает оба замера."""
        self._session.clear_tape()
        self._set_status("Замеры сброшены")
        self._refresh()

    def action_measure_step(self, length: float) -> None:
        """Делает измеренную длину шагом сдвига."""
        try:
            step = min(max(length, STEP_MIN), STEP_MAX)
            self.movement_tab.set_step(step)
        except (DomainError, ValueError) as error:
            self._fail(error)
            return
        self.action_step_changed(step)

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
        self.movement_tab.set_step(settings.step)
        self.btn_apply_commit.setText(f"Сохранить {settings.confirm_key.upper()}")
        self._set_status("Настройки сохранены", "success")

    def action_calibration_changed(self, calibration: Calibration) -> None:
        """Сохраняет новые точки и передаёт их панели."""
        self._settings = _with_calibration(self._settings, calibration)
        self._session.update_settings(self._settings)
        self._apply_calibration_to_panel(calibration)
        self._save_settings()

    def action_diagnostics(self) -> None:
        """Проверяет, доходят ли клики и вставка до панели игры."""
        report = self._session.diagnose()
        level = "success" if report.all_ok else "error"
        self._set_status(report.message, level)

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
        self._refresh_tape()
        pending = len(self._session.pending_fields())
        self.btn_apply.setEnabled(pending > 0)
        self.btn_apply_commit.setEnabled(pending > 0)

    def _refresh_tape(self) -> None:
        self.measure_tab.update_tape(self._session.tape_points(), self._session.span)


def _with_calibration(settings: Settings, calibration: Calibration) -> Settings:
    return replace(settings, calibration=calibration)


def describe_pose(pose: Pose) -> str:
    """Короткое описание позы для строки состояния и логов."""
    return (
        f"X={pose.x:.2f} Y={pose.y:.2f} Z={pose.z:.2f} "
        f"RX={pose.rx:.2f}° RY={pose.ry:.2f}° RZ={pose.rz:.2f}°"
    )
