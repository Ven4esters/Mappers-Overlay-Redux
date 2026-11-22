"""Вкладка «Повороты»: точная установка угла и повороты шагами."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.domain.pose import Axis
from lsp_overlay.ui.widgets import make_button, make_label, make_number_editor

STEP_PRESETS: tuple[float, ...] = (15.0, 45.0, 90.0, 180.0)

AXIS_TITLES: tuple[tuple[Axis, str], ...] = (
    (Axis.YAW, "RZ — поворот вокруг вертикали"),
    (Axis.PITCH, "RX — наклон вперёд/назад"),
    (Axis.ROLL, "RY — крен влево/вправо"),
)


class RotateTab(QWidget):
    """Повороты пропа по любой оси и ручная установка абсолютного угла."""

    rotate_requested = Signal(str, float)
    angle_set_requested = Signal(str, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._axis = Axis.YAW
        self._step = 90.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self._build_axis_group())
        layout.addWidget(self._build_turn_group())
        layout.addWidget(self._build_absolute_group())
        layout.addStretch(1)

    def _build_axis_group(self) -> QGroupBox:
        group = QGroupBox("Ось вращения")
        column = QVBoxLayout(group)
        self.combo_axis = QComboBox()
        for axis, title in AXIS_TITLES:
            self.combo_axis.addItem(title, axis.value)
        self.combo_axis.currentIndexChanged.connect(self._on_axis_changed)
        column.addWidget(self.combo_axis)
        column.addWidget(
            make_label(
                "Угол учитывается и при движении: проп едет вдоль своих осей.",
                muted=True,
                wrap=True,
            )
        )
        return group

    def _build_turn_group(self) -> QGroupBox:
        group = QGroupBox("Поворот шагами")
        grid = QGridLayout(group)
        grid.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(make_label("Шаг угла", muted=True))
        self.combo_step = QComboBox()
        self.combo_step.setEditable(True)
        self.combo_step.addItems([f"{value:g}°" for value in STEP_PRESETS])
        self.combo_step.setCurrentText("90°")
        self.combo_step.activated.connect(lambda _index: self._apply_step_text())
        line_edit = self.combo_step.lineEdit()
        if line_edit is not None:
            line_edit.editingFinished.connect(self._apply_step_text)
        row.addWidget(self.combo_step, 1)
        grid.addLayout(row, 0, 0, 1, 2)
        for column, (title, sign) in enumerate((("− шаг", -1.0), ("+ шаг", 1.0))):
            button = make_button(title, f"Повернуть на {title.strip(' −+')} шага")
            button.clicked.connect(lambda _checked=False, value=sign: self._turn(value))
            grid.addWidget(button, 1, column)
        for column, (title, degrees) in enumerate(
            (("−90°", -90.0), ("+90°", 90.0), ("180°", 180.0))
        ):
            button = make_button(title, f"Повернуть на {degrees:g}°")
            button.clicked.connect(lambda _checked=False, value=degrees: self._turn(value))
            grid.addWidget(button, 2, column)
        return group

    def _build_absolute_group(self) -> QGroupBox:
        group = QGroupBox("Задать угол")
        row = QHBoxLayout(group)
        row.addWidget(make_label("Абсолютный угол", muted=True))
        self.spin_angle: QDoubleSpinBox = make_number_editor(2, minimum=-180.0, maximum=180.0)
        self.spin_angle.setSuffix("°")
        row.addWidget(self.spin_angle, 1)
        button = make_button(
            "Установить", "Поставить ровно этот угол по выбранной оси", object_name="primaryButton"
        )
        button.clicked.connect(self._emit_absolute)
        row.addWidget(button)
        return group

    def _emit_absolute(self) -> None:
        self.angle_set_requested.emit(self._axis.value, self.spin_angle.value())

    def _turn(self, sign: float) -> None:
        self.rotate_requested.emit(self._axis.value, sign * self._step)

    def _on_axis_changed(self, index: int) -> None:
        self._axis = Axis(self.combo_axis.itemData(index))

    def _apply_step_text(self) -> None:
        text = self.combo_step.currentText().replace("°", "").strip().replace(",", ".")
        try:
            value = abs(float(text))
        except ValueError:
            self.combo_step.setCurrentText(f"{self._step:g}°")
            return
        if value == 0.0:
            return
        self._step = value
        self.combo_step.setCurrentText(f"{value:g}°")

    @property
    def axis(self) -> Axis:
        """Текущая выбранная ось."""
        return self._axis

    @property
    def step(self) -> float:
        """Текущий шаг поворота в градусах."""
        return self._step
