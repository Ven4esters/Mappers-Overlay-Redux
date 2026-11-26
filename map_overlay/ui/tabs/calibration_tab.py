"""Вкладка калибровки: точки полей панели и пустого места для F."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Final

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QGridLayout, QPushButton, QVBoxLayout, QWidget

from map_overlay.application.ports import CursorPort
from map_overlay.config import Settings
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.point import Point
from map_overlay.ui.widgets import (
    SECTION_GAP,
    VALUE_MIN_WIDTH,
    Card,
    ValueField,
    button,
    label,
)

COUNTDOWN_SECONDS: Final = 3
COUNTDOWN_TICK_MS: Final = 1000


@dataclass(frozen=True, slots=True)
class Countdown:
    """Сколько ждать перед снятием точки и как часто обновлять счётчик."""

    seconds: int = COUNTDOWN_SECONDS
    tick_ms: int = COUNTDOWN_TICK_MS


EMPTY_SPOT_KEY: Final = "empty"
EMPTY_SPOT_LABEL: Final = "Пустое место (для F)"

HINT = (
    "«Задать» — наведите курсор точно на цель за 3 секунды, оверлей запомнит точку.\n"
    "«Показать» переводит курсор в сохранённую точку: так проверяют калибровку.\n"
    "Точка, которую ещё не задавали, показана прочерком — «Показать» для неё недоступна."
)
EMPTY_HINT = (
    "Пустое место нужно для «Сохранить F»: оверлей кликает туда, чтобы поле перестало\n"
    "быть активным, и нажимает F.\n"
    "Все шесть точек и пустое место заданы — бейдж калибровки в шапке становится зелёным."
)

NAME_COLUMN_WIDTH: Final = 150


class CalibrationTab(QWidget):
    """Точки полей и точка пустого места — всё, что нужно для обмена с панелью."""

    points_changed = Signal(object)
    empty_point_changed = Signal(object)
    status_message = Signal(str)

    def __init__(
        self,
        *,
        cursor: CursorPort,
        settings: Settings,
        countdown: Countdown | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        countdown = countdown or Countdown()
        self._cursor = cursor
        self._points: dict[Field, Point] = dict(settings.calibration)
        self._empty_point = settings.empty_point
        self._countdown_seconds = countdown.seconds
        self._pending: Callable[[], None] | None = None
        self._pending_label = ""
        self._countdown_key = ""
        self._seconds_left = 0
        self._timer = QTimer(self)
        self._timer.setInterval(countdown.tick_ms)
        self._timer.timeout.connect(self._tick)
        self._value_labels: dict[str, ValueField] = {}
        self._show_buttons: dict[str, QPushButton] = {}
        self._capture_buttons: list[QPushButton] = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(SECTION_GAP)
        card = Card("Точки панели LSP", hint=f"{HINT}\n{EMPTY_HINT}")
        self._card = card
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        row = 0
        for field in PANEL_ORDER:
            self._add_row(
                grid,
                row,
                key=field.value,
                title=field.label,
                on_capture=partial(self.start_capture, field),
                on_show=partial(self.show_point, field),
            )
            row += 1
        self._add_row(
            grid,
            row,
            key=EMPTY_SPOT_KEY,
            title=EMPTY_SPOT_LABEL,
            on_capture=self.start_empty_capture,
            on_show=self.show_empty_point,
        )
        # Поля одинаковой ширины, кнопки стоят сразу за ними: пустое место уходит вправо,
        # а числа остаются в одном столбце.
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(4, 1)
        card.add_layout(grid)
        layout.addWidget(card)
        layout.addStretch(1)
        self._refresh_all()

    def _add_row(
        self,
        grid: QGridLayout,
        row: int,
        *,
        key: str,
        title: str,
        on_capture: Callable[[], None],
        on_show: Callable[[], None],
    ) -> None:
        name = label(title, widget_role="poseField")
        name.setMinimumWidth(NAME_COLUMN_WIDTH)
        # Точка — такое же показание, как координаты: поле с моноширинным числом справа.
        value = ValueField()
        value.setFixedWidth(VALUE_MIN_WIDTH)
        value.setToolTip("Точка ещё не задана: нажмите «Задать»")
        capture = button("Задать", tooltip="Отсчитать 3 секунды и запомнить, где сейчас курсор")
        capture.clicked.connect(lambda _checked=False: on_capture())
        show = button(
            "Показать",
            widget_role="small",
            tooltip="Перевести курсор в сохранённую точку",
        )
        show.setEnabled(False)
        show.clicked.connect(lambda _checked=False: on_show())
        grid.addWidget(name, row, 0)
        grid.addWidget(value, row, 1)
        grid.addWidget(capture, row, 2)
        grid.addWidget(show, row, 3)
        self._value_labels[key] = value
        self._show_buttons[key] = show
        self._capture_buttons.append(capture)

    def points(self) -> dict[Field, Point]:
        """Текущая карта калибровки полей."""
        return dict(self._points)

    def empty_point(self) -> Point | None:
        """Текущая точка пустого места."""
        return self._empty_point

    def start_capture(self, field: Field) -> None:
        """Начать отсчёт и запомнить точку поля."""
        self._begin(f"поле {field.label}", lambda: self.capture_now(field), field.value)

    def start_empty_capture(self) -> None:
        """Начать отсчёт и запомнить точку пустого места."""
        self._begin("пустое место панели", self.capture_empty_now, EMPTY_SPOT_KEY)

    def capture_now(self, field: Field) -> None:
        """Запомнить позицию курсора для поля."""
        point = self._cursor.cursor_position()
        self._points[field] = point
        self._refresh(field.value)
        self.status_message.emit(f"Поле {field.label}: точка {point}")
        self.points_changed.emit(dict(self._points))

    def capture_empty_now(self) -> None:
        """Запомнить позицию курсора для пустого места."""
        point = self._cursor.cursor_position()
        self._empty_point = point
        self._refresh(EMPTY_SPOT_KEY)
        self.status_message.emit(f"Пустое место панели: точка {point}")
        self.empty_point_changed.emit(point)

    def show_point(self, field: Field) -> None:
        """Перевести курсор в сохранённую точку поля."""
        point = self._points.get(field)
        if point is None:
            self.status_message.emit(f"Поле {field.label} ещё не откалибровано")
            return
        self._cursor.move_cursor(point)
        self.status_message.emit(f"Курсор переведён в точку поля {field.label}: {point}")

    def show_empty_point(self) -> None:
        """Перевести курсор в сохранённую точку пустого места."""
        if self._empty_point is None:
            self.status_message.emit("Пустое место панели ещё не откалибровано")
            return
        self._cursor.move_cursor(self._empty_point)
        self.status_message.emit(f"Курсор переведён в пустое место: {self._empty_point}")

    def set_points(self, points: Mapping[Field, Point]) -> None:
        """Заменить карту калибровки (после загрузки настроек)."""
        self._points = dict(points)
        self._refresh_all()

    def set_empty_point(self, point: Point | None) -> None:
        """Показать точку пустого места из настроек."""
        self._empty_point = point
        self._refresh(EMPTY_SPOT_KEY)

    def _begin(self, hint: str, on_finish: Callable[[], None], key: str) -> None:
        self._timer.stop()
        self._pending = on_finish
        self._pending_label = hint
        self._seconds_left = self._countdown_seconds
        self._set_capture_enabled(False)
        self._countdown_key = key
        self._tick()

    def _tick(self) -> None:
        if self._pending is None:
            return
        if not self._timer.isActive():
            self._timer.start()
        if self._seconds_left <= 0:
            finish = self._pending
            self._timer.stop()
            self._pending = None
            self._set_capture_enabled(True)
            finish()
            return
        self._value_labels[self._countdown_key].set_value(f"… {self._seconds_left} с")
        self.status_message.emit(
            f"Наведите курсор на {self._pending_label}: осталось {self._seconds_left} с"
        )
        self._seconds_left -= 1

    def _set_capture_enabled(self, is_enabled: bool) -> None:
        for item in self._capture_buttons:
            item.setEnabled(is_enabled)

    def _refresh_all(self) -> None:
        for field in PANEL_ORDER:
            self._refresh(field.value)
        self._refresh(EMPTY_SPOT_KEY)

    def _refresh(self, key: str) -> None:
        point = self._empty_point if key == EMPTY_SPOT_KEY else self._points.get(Field(key))
        widget = self._value_labels[key]
        widget.set_value(None if point is None else f"{point.x}, {point.y}")
        widget.setToolTip(
            "Точка ещё не задана: нажмите «Задать»" if point is None else f"Точка {point}"
        )
        # «Показать» без сохранённой точки нечего: кнопка выключена, а не обещает переход.
        show = self._show_buttons[key]
        show.setEnabled(point is not None)
        show.setToolTip(
            "Перевести курсор в сохранённую точку" if point is not None else "Сначала задайте точку"
        )
