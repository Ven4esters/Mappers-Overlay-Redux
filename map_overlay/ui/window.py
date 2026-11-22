"""Главное окно оверлея."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from map_overlay import __version__
from map_overlay.application.session import MappingSession, StepResult
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.formatting import format_delta, format_value
from map_overlay.domain.movement import COORD_DECIMALS
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.errors import ConfigError
from map_overlay.ui.tabs.calibration_tab import CalibrationTab
from map_overlay.ui.tabs.movement_tab import MovementTab, pose_text
from map_overlay.ui.tabs.settings_tab import SettingsTab
from map_overlay.ui.tasks import TaskRunner
from map_overlay.ui.widgets import label

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 760
WINDOW_HEIGHT = 720
STATUS_INFO = "info"
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ERROR = "error"
STATUS_ROLES: dict[str, str] = {
    STATUS_INFO: "muted",
    STATUS_OK: "ok",
    STATUS_WARN: "warn",
    STATUS_ERROR: "error",
}


class MainWindow(QMainWindow):
    """Собирает вкладки и управляет сценариями панели."""

    def __init__(self, context: AppContext, *, synchronous_tasks: bool = False) -> None:
        super().__init__()
        self._context = context
        self._session: MappingSession | None = None
        self._pose: Pose | None = None
        self._runner = TaskRunner(synchronous=synchronous_tasks, parent=self)
        self._build()
        self._refresh_header()
        if context.settings_error:
            self._set_status(f"Настройки не загружены: {context.settings_error}", STATUS_ERROR)
        else:
            self._set_status("Выберите поля, нажмите «Считать» и двигайте предмет стрелками.")

    def _build(self) -> None:
        self.setWindowTitle(f"Map Overlay Redux {__version__}")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        central = QWidget(self)
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 10)
        layout.setSpacing(10)
        layout.addWidget(self._build_header(central))

        settings = self._context.settings
        self._tabs = QTabWidget(central)
        self.movement = MovementTab(default_step=settings.default_step)
        self.calibration = CalibrationTab(cursor=self._context.cursor, points=settings.calibration)
        self.settings_tab = SettingsTab(settings=settings, config_path=self._context.config_path)
        self._tabs.addTab(self.movement, "Движение")
        self._tabs.addTab(self.calibration, "Калибровка")
        self._tabs.addTab(self.settings_tab, "Настройки")
        layout.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

        self._status = QLabel("", self)
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        self.statusBar().addWidget(self._status, 1)

        self.movement.capture_requested.connect(self._capture)
        self.movement.move_requested.connect(self._move)
        self.calibration.points_changed.connect(self._calibration_changed)
        self.calibration.status_message.connect(self._set_calibration_status)
        self.settings_tab.settings_saved.connect(self._settings_saved)
        self.settings_tab.status_message.connect(self._set_error_status)

    def _build_header(self, parent: QWidget) -> QWidget:
        header = QWidget(parent)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Map Overlay Redux", widget_role="appTitle"))
        layout.addWidget(label(f"v{__version__}", widget_role="muted"))
        layout.addStretch(1)
        self._calibration_label = label("", widget_role="muted")
        layout.addWidget(self._calibration_label)
        return header

    def _refresh_header(self) -> None:
        points = len(self._context.settings.calibration)
        self._calibration_label.setText(f"Калибровка: {points}/6")

    def tab_titles(self) -> list[str]:
        """Названия вкладок по порядку."""
        return [self._tabs.tabText(index) for index in range(self._tabs.count())]

    def status_text(self) -> str:
        """Текст строки состояния (для тестов и журнала)."""
        return self._status.text()

    def _set_status(self, text: str, kind: str = STATUS_INFO) -> None:
        self._status.setText(text)
        self._status.setProperty("role", STATUS_ROLES.get(kind, STATUS_ROLES[STATUS_INFO]))
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _set_calibration_status(self, text: str) -> None:
        self._set_status(text, STATUS_INFO)

    def _set_error_status(self, text: str) -> None:
        self._set_status(text, STATUS_ERROR)

    def _set_busy(self, busy: bool) -> None:
        self.movement.set_busy(busy)

    def _ensure_session(self) -> MappingSession:
        if self._session is None:
            self._session = self._context.make_session()
        return self._session

    def _capture(self) -> None:
        session = self._ensure_session()
        self._set_busy(True)
        self._set_status("Читаю поля панели…")
        self._runner.submit(session.capture, on_success=self._captured, on_error=self._failed)

    def _captured(self, result: object) -> None:
        pose = cast(Pose, result)
        self._pose = pose
        self.movement.set_pose(pose)
        self.movement.set_warning(self._rotation_warning(pose))
        self._set_busy(False)
        self._set_status(f"Считано: {pose_text(pose)}", STATUS_OK)

    def _move(self, direction: object, step: float) -> None:
        session = self._session
        if session is None or session.pose is None or self._pose is None:
            self._set_status(
                "Сначала нажмите «Считать»: без координат шаг не посчитать", STATUS_WARN
            )
            return
        selected = cast(Direction, direction)
        self._set_busy(True)
        self._set_status(f"Шаг {selected.label} на {step:g} м…")
        self._runner.submit(
            lambda: session.step(selected, step),
            on_success=self._moved,
            on_error=self._failed,
        )

    def _moved(self, result: object) -> None:
        step_result = cast(StepResult, result)
        self._pose = step_result.pose
        self.movement.set_pose(step_result.pose)
        self.movement.set_warning(self._rotation_warning(step_result.pose))
        written = ", ".join(field.label for field in step_result.written) or "ничего"
        self._set_busy(False)
        self._set_status(
            f"Шаг: ΔX {format_delta(step_result.delta_x)} · "
            f"ΔY {format_delta(step_result.delta_y)} → {pose_text(step_result.pose)} · "
            f"записано: {written}",
            STATUS_OK,
        )

    def _failed(self, message: str) -> None:
        logger.warning("Действие не выполнено: %s", message)
        self._set_busy(False)
        self._set_status(message, STATUS_ERROR)

    def _rotation_warning(self, pose: Pose) -> str:
        if not pose.is_rotated:
            return ""
        return (
            f"RX {format_value(pose.rx, COORD_DECIMALS)}° · "
            f"RY {format_value(pose.ry, COORD_DECIMALS)}° · "
            f"RZ {format_value(pose.rz, COORD_DECIMALS)}°. Стрелки двигают по мировым осям: "
            "правила для повёрнутых предметов ещё не заданы."
        )

    def _reset_session(self) -> None:
        self._session = None
        self._pose = None
        self.movement.set_pose(None)
        self.movement.set_warning("")

    def _calibration_changed(self, points: object) -> None:
        calibration = cast("Mapping[Field, Point]", points)
        try:
            self._context.save_settings(self._context.settings.with_calibration(calibration))
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self._reset_session()
        self._refresh_header()
        missing = self._context.settings.missing_points()
        if missing:
            titles = ", ".join(field.label for field in missing)
            self._set_status(f"Калибровка сохранена. Не хватает полей: {titles}", STATUS_WARN)
        else:
            self._set_status("Калибровка сохранена. Нажмите «Считать».")

    def _settings_saved(self, settings: object) -> None:
        new_settings = cast(Settings, settings)
        try:
            self._context.save_settings(new_settings)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self._reset_session()
        self.movement.set_default_step(new_settings.default_step)
        self.calibration.set_points(new_settings.calibration)
        self._refresh_header()
        self._set_status("Настройки сохранены. Нажмите «Считать» заново.", STATUS_OK)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - имя из Qt
        """Дождаться фоновой задачи, чтобы не оставить поток висеть."""
        self._runner.shutdown()
        super().closeEvent(event)
