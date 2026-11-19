from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ..models import ROT_FIELDS


def make_number_spin(
    minimum: float,
    maximum: float,
    decimals: int = 4,
    step: float = 0.1,
    suffix: str = "",
    no_buttons: bool = True,
) -> QDoubleSpinBox:
    """Создаёт компактный числовой спинбокс без кнопок-стрелок (в стиле игрового оверлея)."""
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    if suffix:
        spin.setSuffix(suffix)
    if no_buttons:
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    return spin


def make_button(text: str, tooltip: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def make_label(text: str, word_wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(word_wrap)
    return lbl


class CoordinatesBox(QGroupBox):
    """Блок из 6 полей (X, Y, Z, RX, RY, RZ) с ручным редактированием координат объекта."""

    field_edited = Signal(str)

    def __init__(self, pos_decimals: int = 4, rot_decimals: int = 3, parent: QWidget | None = None) -> None:
        super().__init__("Текущие координаты и углы (-180° .. 180°)", parent)
        grid = QGridLayout(self)
        grid.setSpacing(4)

        self.spins: dict[str, QDoubleSpinBox] = {}
        pos_fields = [("x", "X:"), ("y", "Y:"), ("z", "Z:")]
        rot_fields = [("rx", "RX:"), ("ry", "RY:"), ("rz", "RZ:")]

        for row, fields in enumerate((pos_fields, rot_fields)):
            for col, (fname, title) in enumerate(fields):
                is_rot = fname in ROT_FIELDS
                spin = make_number_spin(
                    minimum=-180.0 if is_rot else -99999.0,
                    maximum=180.0 if is_rot else 99999.0,
                    decimals=rot_decimals if is_rot else pos_decimals,
                    step=5.0 if is_rot else 0.1,
                    suffix="°" if is_rot else "",
                )
                spin.editingFinished.connect(lambda f=fname: self.field_edited.emit(f))
                self.spins[fname] = spin

                cell = QHBoxLayout()
                cell.setSpacing(3)
                cell.addWidget(QLabel(title))
                cell.addWidget(spin, 1)
                grid.addLayout(cell, row, col)

    def set_values(self, values: dict[str, float]) -> None:
        for fname, spin in self.spins.items():
            if fname in values:
                with QSignalBlocker(spin):
                    spin.setValue(values[fname])

    def set_decimals(self, decimals: dict[str, int]) -> None:
        for fname, spin in self.spins.items():
            with QSignalBlocker(spin):
                spin.setDecimals(decimals[fname])

    def value_of(self, field_name: str) -> float:
        return float(self.spins[field_name].value())
