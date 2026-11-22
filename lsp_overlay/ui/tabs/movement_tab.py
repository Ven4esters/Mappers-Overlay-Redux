"""Вкладка «Движение»: крестовина из 8 направлений, высота и редакторы полей."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.config import Settings
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.formatting import format_angle, format_length
from lsp_overlay.domain.pose import Pose
from lsp_overlay.ui.widgets import make_button, make_label, make_number_editor

PAD_BUTTON_WIDTH = 40
FIELD_LABEL_WIDTH = 20
STEP_MIN = 0.0001
STEP_MAX = 500.0
HALF = 0.5
DOUBLE = 2.0

ARROWS: tuple[tuple[Direction, str, int, int], ...] = (
    (Direction.NORTH_WEST, "↖", 0, 0),
    (Direction.NORTH, "↑", 0, 1),
    (Direction.NORTH_EAST, "↗", 0, 2),
    (Direction.WEST, "←", 1, 0),
    (Direction.EAST, "→", 1, 2),
    (Direction.SOUTH_WEST, "↙", 2, 0),
    (Direction.SOUTH, "↓", 2, 1),
    (Direction.SOUTH_EAST, "↘", 2, 2),
)


class MovementTab(QWidget):
    """Кнопки сдвига и ручной ввод шести полей."""

    move_requested = Signal(str, float)
    step_changed = Signal(float)
    field_edited = Signal(str, float)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._step = settings.step
        self._editors: dict[FieldKey, QDoubleSpinBox] = {}
        self._is_updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self._build_pad())
        layout.addWidget(self._build_step_row())
        layout.addWidget(self._build_coordinates())
        layout.addStretch(1)

    # ------------------------------------------------------------------ сборка
    def _build_pad(self) -> QGroupBox:
        group = QGroupBox("Движение")
        row = QHBoxLayout(group)
        row.setSpacing(6)
        pad = QWidget()
        grid = QGridLayout(pad)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        for direction, arrow, grid_row, grid_column in ARROWS:
            button = make_button(
                arrow,
                f"Сдвинуть {self._direction_hint(direction)}",
                object_name="arrowButton",
            )
            button.setMinimumWidth(PAD_BUTTON_WIDTH)
            button.clicked.connect(
                lambda _checked=False, value=direction.value: self._emit_move(value)
            )
            grid.addWidget(button, grid_row, grid_column)
        self.lbl_step = QLabel(f"{self._step:g} м")
        self.lbl_step.setObjectName("stepLabel")
        self.lbl_step.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_step.setToolTip("Текущий шаг сдвига")
        grid.addWidget(self.lbl_step, 1, 1)
        row.addWidget(pad, 1)
        column = QVBoxLayout()
        column.setSpacing(4)
        for direction, arrow, hint in (
            (Direction.UP, "↑", "выше"),
            (Direction.DOWN, "↓", "ниже"),
        ):
            button = make_button(arrow, f"Сдвинуть {hint}", object_name="arrowButton")
            button.setMinimumWidth(PAD_BUTTON_WIDTH)
            button.clicked.connect(
                lambda _checked=False, value=direction.value: self._emit_move(value)
            )
            column.addWidget(button)
        row.addLayout(column)
        return group

    def _build_step_row(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(make_label("Шаг", muted=True))
        self.combo_step = QComboBox()
        self.combo_step.setEditable(True)
        self.combo_step.addItems([f"{value:g}" for value in self._settings.step_presets])
        self.combo_step.setCurrentText(f"{self._step:g}")
        self.combo_step.setToolTip("Шаг сдвига в метрах. Можно ввести своё значение.")
        self.combo_step.activated.connect(self._on_step_selected)
        line_edit = self.combo_step.lineEdit()
        if line_edit is not None:
            line_edit.editingFinished.connect(self._on_step_typed)
        row.addWidget(self.combo_step, 1)
        for title, factor, tip in (
            ("÷2", HALF, "Уменьшить шаг вдвое"),
            ("×2", DOUBLE, "Увеличить шаг вдвое"),
        ):
            button = make_button(title, tip, object_name="stepButton")
            button.clicked.connect(lambda _checked=False, value=factor: self._scale_step(value))
            row.addWidget(button)
        return holder

    def _build_coordinates(self) -> QGroupBox:
        group = QGroupBox("Координаты и углы (правка вручную)")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        translation = (FieldKey.X, FieldKey.Y, FieldKey.Z)
        rotation = (FieldKey.RX, FieldKey.RY, FieldKey.RZ)
        for column, (key, title) in enumerate(zip(translation, ("X", "Y", "Z"), strict=True)):
            label = make_label(title, muted=True)
            label.setMinimumWidth(FIELD_LABEL_WIDTH)
            grid.addWidget(label, 0, column * 2)
            editor = make_number_editor(self._settings.length_decimals)
            editor.editingFinished.connect(lambda key=key: self._on_editor_finished(key))
            self._editors[key] = editor
            grid.addWidget(editor, 0, column * 2 + 1)
        for column, (key, title) in enumerate(zip(rotation, ("RX", "RY", "RZ"), strict=True)):
            label = make_label(title, muted=True)
            label.setMinimumWidth(FIELD_LABEL_WIDTH)
            grid.addWidget(label, 1, column * 2)
            editor = make_number_editor(2, minimum=-180.0, maximum=180.0)
            editor.setSuffix("°")
            editor.editingFinished.connect(lambda key=key: self._on_editor_finished(key))
            self._editors[key] = editor
            grid.addWidget(editor, 1, column * 2 + 1)
        return group

    # ------------------------------------------------------------------ события
    def _emit_move(self, direction: str) -> None:
        self.move_requested.emit(direction, self._step)

    def _on_step_selected(self, _index: int) -> None:
        self._apply_step_text(self.combo_step.currentText())

    def _on_step_typed(self) -> None:
        self._apply_step_text(self.combo_step.currentText())

    def _apply_step_text(self, text: str) -> None:
        try:
            value = float(text.strip().replace(",", "."))
        except ValueError:
            self.combo_step.setCurrentText(f"{self._step:g}")
            return
        clamped = min(max(value, STEP_MIN), STEP_MAX)
        self.set_step(clamped)
        self.step_changed.emit(clamped)

    def _scale_step(self, factor: float) -> None:
        self.set_step(min(max(self._step * factor, STEP_MIN), STEP_MAX))
        self.step_changed.emit(self._step)

    def _on_editor_finished(self, key: FieldKey) -> None:
        if self._is_updating:
            return
        self.field_edited.emit(key.value, self._editors[key].value())

    # ------------------------------------------------------------------- вывод
    def set_step(self, step: float) -> None:
        """Показывает шаг в комбобоксе и по центру крестовины."""
        self._step = step
        self.combo_step.setCurrentText(f"{step:g}")
        self.lbl_step.setText(f"{step:g} м")

    def update_pose(self, pose: Pose, pending: tuple[FieldKey, ...]) -> None:
        """Показывает значения полей и подсвечивает неприменённые."""
        self._is_updating = True
        try:
            for key, editor in self._editors.items():
                value = {
                    FieldKey.X: pose.x,
                    FieldKey.Y: pose.y,
                    FieldKey.Z: pose.z,
                    FieldKey.RX: pose.rx,
                    FieldKey.RY: pose.ry,
                    FieldKey.RZ: pose.rz,
                }[key]
                editor.setValue(value)
                editor.setToolTip(
                    format_angle(value) if key.value.startswith("r") else format_length(value)
                )
                editor.setProperty("pending", key in pending)
                editor.style().unpolish(editor)
                editor.style().polish(editor)
        finally:
            self._is_updating = False

    @staticmethod
    def _direction_hint(direction: Direction) -> str:
        return {
            Direction.NORTH: "вперёд",
            Direction.SOUTH: "назад",
            Direction.EAST: "вправо",
            Direction.WEST: "влево",
            Direction.NORTH_EAST: "вперёд-вправо",
            Direction.NORTH_WEST: "вперёд-влево",
            Direction.SOUTH_EAST: "назад-вправо",
            Direction.SOUTH_WEST: "назад-влево",
            Direction.UP: "вверх",
            Direction.DOWN: "вниз",
        }[direction]

    @property
    def editors(self) -> dict[FieldKey, QDoubleSpinBox]:
        """Редакторы полей (нужны тестам и окну)."""
        return self._editors
