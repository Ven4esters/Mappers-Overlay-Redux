from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import format_number


class QuickPanel(QWidget):
    """
    Компактная панель основных действий: шаг, крестовина движения и быстрые повороты.
    Ничего лишнего — используется в главном окне вместо большой вкладки.
    """

    move_requested = Signal(float, float, float)  # right, forward, up
    rotate_requested = Signal(float)
    step_changed = Signal(float)

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build()
        self.set_step_value(settings.step)

    # ------------------------------------------------------------------ сборка
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        pad_row = QHBoxLayout()
        pad_row.setSpacing(6)
        pad_row.addLayout(self._build_dpad(), 1)
        pad_row.addLayout(self._build_vertical(), 0)
        layout.addLayout(pad_row)

        layout.addLayout(self._build_step_row())
        layout.addLayout(self._build_rotate_row())

    def _nav_button(self, text: str, tooltip: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("btnDpad")
        btn.setToolTip(tooltip)
        btn.setMinimumHeight(30)
        btn.clicked.connect(slot)
        return btn

    def _build_dpad(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(3)

        forward = self._nav_button("▲", "Сдвинуть вперёд на один шаг (Alt+↑)", lambda: self.move_requested.emit(0.0, 1.0, 0.0))
        back = self._nav_button("▼", "Сдвинуть назад на один шаг (Alt+↓)", lambda: self.move_requested.emit(0.0, -1.0, 0.0))
        left = self._nav_button("◄", "Сдвинуть влево на один шаг (Alt+←)", lambda: self.move_requested.emit(-1.0, 0.0, 0.0))
        right = self._nav_button("►", "Сдвинуть вправо на один шаг (Alt+→)", lambda: self.move_requested.emit(1.0, 0.0, 0.0))

        self.lbl_center = QLabel("0°")
        self.lbl_center.setObjectName("dpadCenter")
        self.lbl_center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_center.setMinimumSize(46, 30)

        grid.addWidget(forward, 0, 1)
        grid.addWidget(left, 1, 0)
        grid.addWidget(self.lbl_center, 1, 1)
        grid.addWidget(right, 1, 2)
        grid.addWidget(back, 2, 1)
        return grid

    def _build_vertical(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(3)
        up = self._nav_button("↥", "Поднять объект вверх (Alt+PageUp)", lambda: self.move_requested.emit(0.0, 0.0, 1.0))
        down = self._nav_button("↧", "Опустить объект вниз (Alt+PageDown)", lambda: self.move_requested.emit(0.0, 0.0, -1.0))
        up.setMaximumWidth(40)
        down.setMaximumWidth(40)
        column.addWidget(up)
        column.addWidget(down)
        return column

    def _build_step_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(QLabel("Шаг"))

        self.combo_step = QComboBox()
        self.combo_step.setEditable(True)
        self.combo_step.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_step.setToolTip("Шаг сдвига в метрах. Можно выбрать из списка или вписать своё число.")
        for value in self._settings.step_presets:
            self.combo_step.addItem(format_number(value, 3), float(value))
        self.combo_step.activated.connect(lambda _i: self._apply_step_from_combo())
        self.combo_step.lineEdit().editingFinished.connect(self._apply_step_from_combo)  # type: ignore[union-attr]
        row.addWidget(self.combo_step, 1)

        btn_half = QPushButton("÷2")
        btn_half.setMaximumWidth(34)
        btn_half.setToolTip("Уменьшить шаг вдвое")
        btn_half.clicked.connect(lambda: self._set_step(max(0.0005, self._current_step() / 2.0)))
        row.addWidget(btn_half)

        btn_double = QPushButton("×2")
        btn_double.setMaximumWidth(34)
        btn_double.setToolTip("Увеличить шаг вдвое")
        btn_double.clicked.connect(lambda: self._set_step(min(500.0, self._current_step() * 2.0)))
        row.addWidget(btn_double)
        return row

    def _build_rotate_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(3)
        for label, degrees, tip in (
            ("−90°", -90.0, "Повернуть против часовой стрелки на 90°"),
            ("+90°", 90.0, "Повернуть по часовой стрелке на 90°"),
            ("180°", 180.0, "Развернуть на 180°"),
        ):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, d=degrees: self.rotate_requested.emit(d))
            row.addWidget(btn, 1)
        return row

    # ------------------------------------------------------------------ состояние
    def _current_step(self) -> float:
        return self._parse_step_text(self.combo_step.currentText())

    @staticmethod
    def _parse_step_text(text: str) -> float:
        clean = text.replace(",", ".").replace("м", "").strip()
        try:
            value = float(clean)
        except ValueError:
            return 0.1
        return min(500.0, max(0.0005, value))

    def _apply_step_from_combo(self) -> None:
        self._set_step(self._parse_step_text(self.combo_step.currentText()))

    def _set_step(self, value: float) -> None:
        value = min(500.0, max(0.0005, float(value)))
        self.combo_step.setCurrentText(format_number(value, 3))
        self.lbl_center.setText(f"{format_number(value, 3)} м")
        if abs(float(self._settings.step) - value) > 1e-9:
            self.step_changed.emit(value)

    def set_step_value(self, value: float) -> None:
        """Программно выставляет шаг (без лишних сигналов, если значение не изменилось)."""
        self._set_step(value)

    def set_heading(self, rz: float) -> None:
        self.lbl_center.setToolTip(f"Текущий угол RZ: {rz:+.2f}°")
