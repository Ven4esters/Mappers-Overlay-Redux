"""Небольшие виджеты, из которых собираются вкладки."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.formatting import format_value
from map_overlay.domain.movement import ALT_TITLES, COORD_DECIMALS, DIAGONAL_TITLES
from map_overlay.domain.pose import Pose

CARD_MARGIN: Final = 14
CARD_SPACING: Final = 10
GRID_SPACING: Final = 8

ARROW_ROWS: Final[tuple[tuple[Direction | None, ...], ...]] = (
    (Direction.FORWARD_LEFT, Direction.FORWARD, Direction.FORWARD_RIGHT),
    (Direction.LEFT, None, Direction.RIGHT),
    (Direction.BACK_LEFT, Direction.BACK, Direction.BACK_RIGHT),
)


def role(widget: QWidget, value: str) -> QWidget:
    """Пометить виджет для стилей Qt (``QLabel[role="..."]``)."""
    widget.setProperty("role", value)
    return widget


def label(text: str = "", *, widget_role: str = "muted") -> QLabel:
    """Подпись с ролью из темы."""
    item = QLabel(text)
    item.setProperty("role", widget_role)
    item.setWordWrap(True)
    return item


def button(text: str, *, widget_role: str | None = None, tooltip: str = "") -> QPushButton:
    """Кнопка с необязательной ролью (например, ``primary``)."""
    item = QPushButton(text)
    if widget_role:
        item.setProperty("role", widget_role)
    if tooltip:
        item.setToolTip(tooltip)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    return item


class Card(QFrame):
    """Карточка с заголовком: контейнер для группы элементов."""

    def __init__(self, title: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(CARD_MARGIN, CARD_MARGIN, CARD_MARGIN, CARD_MARGIN)
        outer.setSpacing(CARD_SPACING)
        outer.addWidget(label(title, widget_role="cardTitle"))
        self.body = QVBoxLayout()
        self.body.setSpacing(CARD_SPACING)
        outer.addLayout(self.body)

    def add(self, widget: QWidget, *, stretch: int = 0) -> None:
        """Добавить виджет в тело карточки."""
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout: QLayout) -> None:
        """Добавить строку/сетку в тело карточки."""
        self.body.addLayout(layout)


class PoseGrid(QWidget):
    """Шесть полей позы: X, Y, Z сверху, RX, RY, RZ снизу."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(GRID_SPACING)
        self._values: dict[Field, QLabel] = {}
        rows: tuple[tuple[Field, ...], ...] = (
            (Field.X, Field.Y, Field.Z),
            (Field.RX, Field.RY, Field.RZ),
        )
        for row_index, fields in enumerate(rows):
            for column, field in enumerate(fields):
                grid.addWidget(self._cell(field), row_index, column)

    def _cell(self, field: Field) -> QWidget:
        cell = QWidget(self)
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(label(field.label, widget_role="poseField"))
        value = QLabel("—")
        value.setProperty("role", "poseValue")
        value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(value)
        self._values[field] = value
        return cell

    def set_pose(self, pose: Pose | None) -> None:
        """Показать позу или прочерки, если она ещё не считана."""
        for field, widget in self._values.items():
            widget.setText("—" if pose is None else format_value(pose.value(field), COORD_DECIMALS))


class DirectionPad(QWidget):
    """Крестовина из восьми стрелок с подписью шага в центре."""

    direction_clicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(GRID_SPACING)
        self._buttons: list[QPushButton] = []
        self._by_direction: dict[Direction, QPushButton] = {}
        self._enabled = True
        self._alt_mode = False
        self._step_label = QLabel("шаг")
        self._step_label.setProperty("role", "stepLabel")
        self._step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for row, line in enumerate(ARROW_ROWS):
            for column, direction in enumerate(line):
                if direction is None:
                    grid.addWidget(self._step_label, row, column)
                else:
                    grid.addWidget(self._arrow(direction), row, column)

    def _axis_tooltip(self, direction: Direction) -> str:
        """Подсказка для обычного режима: прямые — оси, диагонали — ``RX`` и ``RY``."""
        if direction.is_diagonal:
            return (
                f"{direction.label}: {DIAGONAL_TITLES[direction]} на шаг "
                f"(RX ведёт Y, RY ведёт X и сжимает Z)"
            )
        dx, dy = direction.axes
        parts = []
        if dx:
            parts.append(f"X {'−' if dx < 0 else '+'}")
        if dy:
            parts.append(f"Y {'−' if dy < 0 else '+'}")
        return f"{direction.label}: {', '.join(parts)} на шаг"

    def _arrow(self, direction: Direction) -> QPushButton:
        item = button(direction.glyph, widget_role="arrow", tooltip=self._axis_tooltip(direction))
        item.clicked.connect(lambda _checked=False, d=direction: self.direction_clicked.emit(d))
        self._buttons.append(item)
        self._by_direction[direction] = item
        return item

    def button(self, direction: Direction) -> QPushButton:
        """Кнопка направления (нужна тестам и подсказкам)."""
        return self._by_direction[direction]

    def set_alt_mode(self, enabled: bool) -> None:
        """Показать в подсказках режим высоты: ``Num 8`` — вверх, ``Num 2`` — вниз."""
        self._alt_mode = enabled
        for direction, item in self._by_direction.items():
            if enabled and direction in ALT_TITLES:
                item.setToolTip(f"{direction.label}: {ALT_TITLES[direction]} на шаг (Alt)")
            elif direction.is_diagonal:
                item.setToolTip(self._axis_tooltip(direction))
            else:
                item.setToolTip(self._axis_tooltip(direction))

    def set_step_text(self, text: str) -> None:
        """Подпись в центре крестовины."""
        self._step_label.setText(text)

    def set_enabled(self, is_enabled: bool) -> None:
        """Включить или выключить все стрелки."""
        self._enabled = is_enabled
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        """Включить или выключить все стрелки (режим высоты ничего не блокирует)."""
        for item in self._by_direction.values():
            item.setEnabled(self._enabled)


def add_row(layout: QHBoxLayout, widgets: Iterable[QWidget], *, stretch_last: bool = True) -> None:
    """Добавить виджеты в строку, растянув последний."""
    items = list(widgets)
    for index, widget in enumerate(items):
        layout.addWidget(widget)
        if stretch_last and index == len(items) - 1:
            layout.setStretch(index, 1)
