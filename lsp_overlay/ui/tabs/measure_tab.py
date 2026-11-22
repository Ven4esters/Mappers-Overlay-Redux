"""Вкладка «Рулетка»: замер габаритов объекта по двум точкам."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.domain.catalog import Dimension
from lsp_overlay.domain.formatting import format_angle, format_length
from lsp_overlay.domain.measure import MeasureSlot, Span
from lsp_overlay.domain.pose import Pose
from lsp_overlay.ui.widgets import make_button, make_label

LABEL_WIDTH = 132
EMPTY_TEXT = "—"
HINT = (
    "Поставьте проп у одного края объекта и нажмите «Точка A», затем у другого — «Точка B». "
    "Выберите габарит и нажмите «В размер». Длина и ширина считаются вдоль осей самого "
    "предмета, толщина — по вертикали: поставьте проп на верхнюю и на нижнюю грань плиты. "
    "Измеренные габариты ждут на вкладке «Объекты»."
)


class MeasureTab(QWidget):
    """Рулетка: два замера, расстояние и запись габарита."""

    remember_requested = Signal(str)
    reset_requested = Signal()
    step_requested = Signal(float)
    dimension_requested = Signal(str)
    status_message = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._span: Span | None = None
        self._points: dict[MeasureSlot, Pose] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self._build_points())
        layout.addWidget(self._build_result(), 1)
        layout.addWidget(self._build_actions())
        layout.addWidget(make_label(HINT, muted=True, wrap=True))

    # ------------------------------------------------------------------ сборка
    def _build_points(self) -> QGroupBox:
        group = QGroupBox("Точки замера")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self._point_labels: dict[MeasureSlot, QLabel] = {}
        for row, slot in enumerate((MeasureSlot.FIRST, MeasureSlot.SECOND)):
            grid.addWidget(make_label(f"Точка {slot.label}", muted=True), row, 0)
            value = QLabel(EMPTY_TEXT)
            value.setObjectName("measureValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._point_labels[slot] = value
            grid.addWidget(value, row, 1)
            button = make_button(
                "Запомнить",
                f"Взять текущие координаты пропа как точку {slot.label}",
            )
            button.clicked.connect(
                lambda _checked=False, value=slot.value: self.remember_requested.emit(value)
            )
            grid.addWidget(button, row, 2)
        return group

    def _build_result(self) -> QGroupBox:
        group = QGroupBox("Результат")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)
        self._value_labels: dict[str, QLabel] = {}
        rows = (
            ("distance", "По прямой"),
            ("planar", "В плане (длина)"),
            ("vertical", "Перепад высоты"),
            ("dx", "Разница X"),
            ("dy", "Разница Y"),
            ("dz", "Разница Z"),
            ("heading", "Направление A → B"),
        )
        for row, (key, title) in enumerate(rows):
            label = make_label(title, muted=True)
            label.setMinimumWidth(LABEL_WIDTH)
            grid.addWidget(label, row, 0)
            value = QLabel(EMPTY_TEXT)
            value.setObjectName("measureValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._value_labels[key] = value
            grid.addWidget(value, row, 1)
        grid.setRowStretch(len(rows), 1)
        return group

    def _build_actions(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_step = make_button(
            "Шаг = длина",
            "Поставить длину в плане как шаг сдвига, чтобы ставить объекты вплотную",
            object_name="primaryButton",
        )
        self.btn_step.clicked.connect(self._on_step_clicked)
        self.btn_copy = make_button("Копировать", "Скопировать результат замера в буфер обмена")
        self.btn_copy.clicked.connect(self._on_copy_clicked)
        self.btn_reset = make_button("Сбросить", "Забыть оба замера")
        self.btn_reset.clicked.connect(self.reset_requested.emit)
        for button in (self.btn_step, self.btn_copy, self.btn_reset):
            row.addWidget(button, 1)
        column.addLayout(row)
        second = QHBoxLayout()
        second.setSpacing(4)
        second.addWidget(make_label("Габарит", muted=True))
        self.combo_dimension = QComboBox()
        for dimension in Dimension:
            self.combo_dimension.addItem(dimension.label, dimension.value)
        self.combo_dimension.setToolTip("Каким габаритом считать текущий замер")
        second.addWidget(self.combo_dimension, 1)
        self.btn_dimension = make_button(
            "В размер",
            "Записать текущий замер в выбранный габарит и передать его на вкладку «Объекты»",
        )
        self.btn_dimension.clicked.connect(self._on_dimension_clicked)
        second.addWidget(self.btn_dimension)
        column.addLayout(second)
        return holder

    # ------------------------------------------------------------------ события
    def _on_step_clicked(self) -> None:
        if self._span is None or self._span.is_degenerate:
            self.status_message.emit("Сначала сделайте два разных замера", "warning")
            return
        self.step_requested.emit(self._span.length_for_step())

    def _on_dimension_clicked(self) -> None:
        self.dimension_requested.emit(str(self.combo_dimension.currentData()))

    def _on_copy_clicked(self) -> None:
        text = self.result_text()
        if not text:
            self.status_message.emit("Пока нечего копировать — сделайте два замера", "warning")
            return
        QGuiApplication.clipboard().setText(text)
        self.status_message.emit("Замер скопирован", "success")

    # ------------------------------------------------------------------- вывод
    def update_tape(self, points: dict[MeasureSlot, Pose], span: Span | None) -> None:
        """Показывает сохранённые точки и посчитанный по ним замер."""
        self._points = dict(points)
        self._span = span
        for slot, label in self._point_labels.items():
            pose = self._points.get(slot)
            label.setText(EMPTY_TEXT if pose is None else _describe_point(pose))
        self._update_values(span)
        self.btn_step.setEnabled(span is not None and not span.is_degenerate)
        self.btn_copy.setEnabled(span is not None)
        self.btn_dimension.setEnabled(span is not None and not span.is_degenerate)

    def _update_values(self, span: Span | None) -> None:
        if span is None:
            for label in self._value_labels.values():
                label.setText(EMPTY_TEXT)
            return
        dx, dy, dz = span.delta
        values = {
            "distance": f"{format_length(span.distance, 3)} м",
            "planar": f"{format_length(span.planar, 3)} м",
            "vertical": f"{format_length(span.vertical, 3)} м",
            "dx": format_length(dx, 3),
            "dy": format_length(dy, 3),
            "dz": format_length(dz, 3),
            "heading": format_angle(span.heading, 1),
        }
        for key, text in values.items():
            self._value_labels[key].setText(text)

    def value_text(self, key: str) -> str:
        """Текст строки результата (для тестов и подсказок)."""
        return self._value_labels[key].text()

    def point_text(self, slot: str) -> str:
        """Текст сохранённой точки замера."""
        return self._point_labels[MeasureSlot(slot)].text()

    def result_text(self) -> str:
        """Текст замера для буфера обмена."""
        span = self._span
        if span is None:
            return ""
        dx, dy, dz = span.delta
        return (
            f"Замер: {format_length(span.planar, 3)} м в плане, "
            f"{format_length(span.distance, 3)} м по прямой, "
            f"по вертикали {format_length(span.vertical, 3)} м; "
            f"ΔX={format_length(dx, 3)} ΔY={format_length(dy, 3)} ΔZ={format_length(dz, 3)}; "
            f"направление {format_angle(span.heading, 1)}"
        )


def _describe_point(pose: Pose) -> str:
    return f"{format_length(pose.x, 2)}, {format_length(pose.y, 2)}, {format_length(pose.z, 2)}"
