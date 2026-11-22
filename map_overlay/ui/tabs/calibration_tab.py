"""Вкладка калибровки: точка экрана для каждого поля панели."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from map_overlay.application.ports import CursorPort
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.point import Point
from map_overlay.ui.widgets import Card, button, label

COUNTDOWN_SECONDS: Final = 3
COUNTDOWN_TICK_MS: Final = 1000

HINT: Final = (
    "Нажмите «Задать» и за 3 секунды наведите курсор точно на поле панели LSP — "
    "оверлей запомнит эту точку. «Показать» переводит курсор в сохранённую точку, "
    "чтобы проверить калибровку."
)


class CalibrationTab(QWidget):
    """Пять-шесть точек — и панель готова к работе."""

    points_changed = Signal(object)
    status_message = Signal(str)

    def __init__(
        self,
        *,
        cursor: CursorPort,
        points: Mapping[Field, Point],
        countdown_seconds: int = COUNTDOWN_SECONDS,
        tick_ms: int = COUNTDOWN_TICK_MS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cursor = cursor
        self._points: dict[Field, Point] = dict(points)
        self._countdown_seconds = countdown_seconds
        self._pending: Field | None = None
        self._seconds_left = 0
        self._timer = QTimer(self)
        self._timer.setInterval(tick_ms)
        self._timer.timeout.connect(self._tick)
        self._value_labels: dict[Field, QLabel] = {}
        self._capture_buttons: dict[Field, QPushButton] = {}
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        hint = label(HINT, widget_role="muted")
        layout.addWidget(hint)
        card = Card("Поля панели")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for row, field in enumerate(PANEL_ORDER):
            title = label(field.label, widget_role="poseField")
            title.setMinimumWidth(34)
            value = QLabel("не задано")
            value.setProperty("role", "muted")
            capture = button("Задать", widget_role="primary")
            capture.clicked.connect(lambda _checked=False, f=field: self.start_capture(f))
            show = button("Показать")
            show.clicked.connect(lambda _checked=False, f=field: self.show_point(f))
            grid.addWidget(title, row, 0)
            grid.addWidget(value, row, 1)
            grid.addWidget(capture, row, 2)
            grid.addWidget(show, row, 3)
            self._value_labels[field] = value
            self._capture_buttons[field] = capture
        grid.setColumnStretch(1, 1)
        card.add_layout(grid)
        layout.addWidget(card)
        layout.addStretch(1)
        self._refresh_all()

    def points(self) -> dict[Field, Point]:
        """Текущая карта калибровки."""
        return dict(self._points)

    def start_capture(self, field: Field) -> None:
        """Начать отсчёт и затем взять позицию курсора."""
        self._timer.stop()
        self._pending = field
        self._seconds_left = self._countdown_seconds
        self._set_capture_enabled(False)
        self._tick()

    def capture_now(self, field: Field) -> None:
        """Запомнить текущую позицию курсора для поля."""
        point = self._cursor.cursor_position()
        self._points[field] = point
        self._refresh(field)
        self.status_message.emit(f"Поле {field.label}: точка {point}")
        self.points_changed.emit(dict(self._points))

    def show_point(self, field: Field) -> None:
        """Перевести курсор в сохранённую точку поля."""
        point = self._points.get(field)
        if point is None:
            self.status_message.emit(f"Поле {field.label} ещё не откалибровано")
            return
        self._cursor.move_cursor(point)
        self.status_message.emit(f"Курсор переведён в точку поля {field.label}: {point}")

    def _tick(self) -> None:
        if self._pending is None:
            return
        if not self._timer.isActive():
            self._timer.start()
        field = self._pending
        if self._seconds_left <= 0:
            self._timer.stop()
            self._pending = None
            self._set_capture_enabled(True)
            self.capture_now(field)
            return
        self._value_labels[field].setText(f"наведите курсор… {self._seconds_left}")
        self.status_message.emit(
            f"Наведите курсор на поле {field.label}: осталось {self._seconds_left} с"
        )
        self._seconds_left -= 1

    def _set_capture_enabled(self, is_enabled: bool) -> None:
        for item in self._capture_buttons.values():
            item.setEnabled(is_enabled)

    def _refresh_all(self) -> None:
        for field in PANEL_ORDER:
            self._refresh(field)

    def _refresh(self, field: Field) -> None:
        point = self._points.get(field)
        widget = self._value_labels[field]
        if point is None:
            widget.setText("не задано")
            widget.setProperty("role", "muted")
        else:
            widget.setText(f"{point.x}, {point.y}")
            widget.setProperty("role", "poseValue")
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def set_points(self, points: Mapping[Field, Point]) -> None:
        """Заменить карту калибровки (после загрузки настроек)."""
        self._points = dict(points)
        self._refresh_all()
