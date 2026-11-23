"""Небольшие виджеты, из которых собираются вкладки."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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
CARD_SPACING: Final = 12
GRID_SPACING: Final = 8
SECTION_GAP: Final = 16
# Расстояние между карточками. Должно быть больше, чем внутри карточки (CARD_SPACING),
# иначе блоки слипаются и непонятно, где кончается один и начинается другой.
ROW_SPACING: Final = 8
LABEL_COLUMN_WIDTH: Final = 66
VALUE_MIN_WIDTH: Final = 170
# Колонка подписей «Поиск»/«Предмет»: поля ввода начинаются с одного места.

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


HINT_LIST_STYLE: Final = "margin:0; padding-left:18px;"


def bullets(*lines: str) -> str:
    """Текст подсказки списком: один пункт на строку, разметка rich text."""
    items = "".join(f"<li>{line}</li>" for line in lines)
    return f"<ul style='{HINT_LIST_STYLE}'>{items}</ul>"


def hint_label(*lines: str) -> QLabel:
    """Подсказка списком: мелкий приглушённый текст, клавиши выделяются ``<b>``."""
    item = label(bullets(*lines), widget_role="hint")
    item.setTextFormat(Qt.TextFormat.RichText)
    return item


class ValueField(QLabel):
    """Поле-показание: моноширинное значение по правому краю, «—» для пустого."""

    def __init__(self, text: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "poseDisplay")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_value(text)

    def set_value(self, text: str | None) -> None:
        """Показать значение или приглушённый прочерк, если данных ещё нет."""
        is_empty = not text
        self.setText(text if text else "—")
        if bool(self.property("empty")) is not is_empty:
            self.setProperty("empty", is_empty)
            self.style().unpolish(self)
            self.style().polish(self)

    def value(self) -> str | None:
        """Значение без прочерка (для тестов и подсказок)."""
        return None if self.property("empty") else self.text()


class AppButton(QPushButton):
    """Кнопка, которая показывает своё состояние курсором: у выключенной — «нельзя»."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._sync_cursor()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - имя из Qt
        """Обновить курсор, когда кнопку включили или выключили."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._sync_cursor()

    def _sync_cursor(self) -> None:
        shape = (
            Qt.CursorShape.PointingHandCursor
            if self.isEnabled()
            else Qt.CursorShape.ForbiddenCursor
        )
        self.setCursor(shape)


def button(
    text: str,
    *,
    widget_role: str | None = None,
    tooltip: str = "",
    danger: bool = False,
) -> AppButton:
    """Кнопка с необязательной ролью (например, ``primary``).

    ``danger`` помечает опасное действие красной рамкой, не меняя размер кнопки:
    свойство ``severity`` складывается с ролью ``small``.
    """
    item = AppButton(text)
    if widget_role:
        item.setProperty("role", widget_role)
    if danger:
        item.setProperty("severity", "danger")
    if tooltip:
        item.setToolTip(tooltip)
    return item


class Card(QFrame):
    """Карточка с заголовком: контейнер для группы элементов."""

    def __init__(self, title: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        # Карточка занимает ровно свою высоту: лишнее место забирает растяжка под ней.
        # Иначе при скрытых строках (мини-версия) карточка раздувалась пустотой.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
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
        self._values: dict[Field, ValueField] = {}
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
        # Значение — поле-показание: моноширинный шрифт и выравнивание по правому краю,
        # чтобы 0.125 и 12.500 стояли друг под другом, а не «плясали».
        value = ValueField()
        layout.addWidget(value)
        self._values[field] = value
        return cell

    def set_pose(self, pose: Pose | None) -> None:
        """Показать позу или прочерки, если она ещё не считана."""
        for field, widget in self._values.items():
            widget.set_value(
                None if pose is None else format_value(pose.value(field), COORD_DECIMALS)
            )
        return

    def alignment_of(self, field: Field) -> Qt.AlignmentFlag:
        """Как выровнено значение поля (для тестов)."""
        return self._values[field].alignment()

    def text_of(self, field: Field) -> str:
        """Что показано в поле (для тестов)."""
        return self._values[field].text()


class CenterMark(QWidget):
    """Нейтральная точка в центре крестовины: не кнопка и не подпись шага."""

    RADIUS: Final = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setToolTip("Центр крестовины: шаг задаётся полем «Шаг» под кнопками")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - имя из Qt
        """Нарисовать точку с едва заметным кольцом."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.setPen(QColor("#2c3a55"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 11, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#55627a"))
        painter.drawEllipse(center, self.RADIUS, self.RADIUS)
        painter.end()


class DirectionPad(QWidget):
    """Крестовина из восьми стрелок с нейтральным центром."""

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
        self.center = CenterMark(self)
        for row, line in enumerate(ARROW_ROWS):
            for column, direction in enumerate(line):
                if direction is None:
                    grid.addWidget(self.center, row, column, Qt.AlignmentFlag.AlignCenter)
                else:
                    grid.addWidget(self._arrow(direction), row, column)

    def _axis_tooltip(self, direction: Direction) -> str:
        """Подсказка для обычного режима: прямые — оси, диагонали — по наклону предмета."""
        if direction.is_diagonal:
            return (
                f"{direction.label}: {DIAGONAL_TITLES[direction]} на шаг "
                f"(без наклона — в горизонтали, с наклоном — по RX и RY)"
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

    def set_enabled(self, is_enabled: bool) -> None:
        """Включить или выключить все стрелки."""
        self._enabled = is_enabled
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        """Включить или выключить все стрелки (режим высоты ничего не блокирует)."""
        for item in self._by_direction.values():
            item.setEnabled(self._enabled)
