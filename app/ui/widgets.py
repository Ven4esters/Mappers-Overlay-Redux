"""Small reusable UI pieces. / Переиспользуемые UI-примитивы."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class SegmentedControl(QWidget):
    """Mutually-exclusive row of checkable buttons (replaces tiny combo boxes).
    Взаимоисключающий ряд кнопок (замена маленьких выпадающих списков).

    ``currentChanged`` carries the selected option id.
    """

    currentChanged = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None) -> None:
        """options: [(id, label), ...] left-to-right. / Варианты слева направо."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for option_id, label in options:
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setObjectName("Segmented")
            button.setFocusPolicy(Qt.StrongFocus)
            button.clicked.connect(lambda _checked=False, key=option_id: self._on_clicked(key))
            self._group.addButton(button)
            self._buttons[option_id] = button
            layout.addWidget(button, stretch=1)

    def _on_clicked(self, option_id: str) -> None:
        self.currentChanged.emit(option_id)

    def set_current(self, option_id: str) -> None:
        button = self._buttons.get(option_id)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def current(self) -> str:
        for option_id, button in self._buttons.items():
            if button.isChecked():
                return option_id
        return next(iter(self._buttons), "")
