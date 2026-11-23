"""Вкладка движения: координаты, шаг и крестовина из восьми стрелок."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QLocale, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from map_overlay.domain.formatting import rounded
from map_overlay.domain.movement import (
    COORD_DECIMALS,
    MAX_STEP,
    MIN_STEP,
    alt_hint,
    validate_step,
)
from map_overlay.domain.pose import Pose
from map_overlay.errors import ValidationError
from map_overlay.ui.widgets import Card, DirectionPad, PoseGrid, button, label

STEP_PRESETS: Final[tuple[str, ...]] = ("0.1", "0.25", "0.5", "1", "2", "5", "10")
STEP_DECIMALS: Final = 3
_HINTS: Final[tuple[str, ...]] = (
    "Одна стрелка — один шаг; те же действия есть на Numpad. Зажмите клавишу — "
    "шаг повторяется сразу за предыдущим, отпустите — движение останавливается.",
    "Одно нажатие Alt включает режим высоты: Num 8 поднимает предмет по локальной "
    "оси Z, Num 2 опускает (при RY ≠ 0 шаг идёт в плоскости X/Z). Остальные "
    "клавиши не меняются: Num 4/6 — по горизонтали, диагонали — по наклону "
    "предмета (без наклона — 45° в плоскости экрана Y/Z, с наклоном — по RX и RY). "
    "Ещё одно нажатие — выключить. "
    "Держать Alt не нужно: пока он зажат, игра не применяет правки панели.",
)
# Подсказки под крестовиной: одни и те же для окна и для режима высоты.


class MovementTab(QWidget):
    """Считать координаты и двигать предмет стрелками."""

    capture_requested = Signal()
    confirm_requested = Signal()
    move_requested = Signal(object, float)
    tilt_toggled = Signal(bool)

    def __init__(self, *, default_step: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pose: Pose | None = None
        self._tilt = False
        self._build(default_step)

    def _build(self, default_step: float) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_pose_card())
        layout.addWidget(self._build_move_card(default_step))
        self._warning = label("", widget_role="warn")
        self._warning.hide()
        layout.addWidget(self._warning)
        layout.addStretch(1)
        self._pad.set_enabled(False)
        self._sync_step_text()

    def _build_pose_card(self) -> Card:
        """Карточка координат и углов с кнопками «Считать» и «Сохранить F»."""
        card = Card("Координаты и углы")
        self._grid = PoseGrid(self)
        card.add(self._grid)
        row = QHBoxLayout()
        self._capture_button = button("Считать", widget_role="primary")
        self._capture_button.clicked.connect(self.capture_requested.emit)
        self._capture_button.setToolTip("Прочитать все шесть полей панели")
        self._confirm_button = button("Сохранить F")
        self._confirm_button.clicked.connect(self.confirm_requested.emit)
        self._confirm_button.setToolTip(
            "Вставить значения, кликнуть в пустое место панели и нажать F"
        )
        row.addWidget(self._capture_button)
        row.addWidget(self._confirm_button)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _build_move_card(self, default_step: float) -> Card:
        """Карточка сдвига: крестовина, шаг, режим высоты и подсказки."""
        card = Card("Сдвиг предмета")
        self._pad = DirectionPad(self)
        self._pad.direction_clicked.connect(self._request_move)
        card.add(self._pad)
        card.add_layout(self._build_step_row(default_step))
        card.add_layout(self._build_mode_row())
        for hint in _HINTS:
            card.add(label(hint, widget_role="muted"))
        return card

    def _build_step_row(self, default_step: float) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label("Шаг", widget_role="muted"))
        self._step_combo = QComboBox(self)
        self._step_combo.setEditable(True)
        self._step_combo.addItems(STEP_PRESETS)
        self._step_combo.setCurrentText(_format_step(default_step))
        self._step_combo.setValidator(QDoubleValidator(MIN_STEP, MAX_STEP, STEP_DECIMALS, self))
        self._step_combo.setLocale(QLocale.c())
        self._step_combo.setMinimumWidth(96)
        self._step_combo.editTextChanged.connect(self._sync_step_text)
        row.addWidget(self._step_combo)
        row.addWidget(label("м", widget_role="muted"))
        row.addStretch(1)
        return row

    def _build_mode_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._tilt_box = QCheckBox("Режим высоты", self)
        self._tilt_box.setToolTip(
            "Num 8 поднимает предмет, Num 2 опускает. Остальные клавиши работают как "
            "обычно. То же делает одно нажатие Alt."
        )
        self._tilt_box.toggled.connect(self.tilt_toggled.emit)
        row.addWidget(self._tilt_box)
        row.addStretch(1)
        self._mode_label = label("8/2 — вперёд/назад", widget_role="muted")
        self._mode_label.setWordWrap(False)
        row.addWidget(self._mode_label)
        return row

    def _request_move(self, direction: object) -> None:
        try:
            step = self.current_step()
        except ValidationError as exc:
            self.set_warning(str(exc))
            return
        self.move_requested.emit(direction, step)

    def _sync_step_text(self, _text: str = "") -> None:
        try:
            step = self.current_step()
        except ValidationError:
            self._pad.set_step_text("шаг?")
            return
        self._pad.set_step_text(f"{rounded(step, STEP_DECIMALS):g} м")

    def current_step(self) -> float:
        """Шаг из поля ввода.

        Raises:
            ValidationError: если число недопустимо.
        """
        raw = self._step_combo.currentText().replace(",", ".").strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValidationError("Шаг должен быть числом") from exc
        return validate_step(value)

    def press_capture(self) -> None:
        """Нажать «Считать» (для тестов и будущих горячих клавиш)."""
        self._capture_button.click()

    def set_default_step(self, step: float) -> None:
        """Показать новый шаг по умолчанию."""
        self._step_combo.setCurrentText(_format_step(step))
        self._sync_step_text()

    def set_pose(self, pose: Pose | None) -> None:
        """Обновить координаты и доступность стрелок."""
        self._pose = pose
        self._grid.set_pose(pose)
        self._pad.set_enabled(pose is not None)
        self._refresh_mode()

    def mode_text(self) -> str:
        """Подпись режима движения (для тестов)."""
        return self._mode_label.text()

    def set_tilt(self, enabled: bool) -> None:
        """Показать, включён ли режим высоты."""
        self._tilt = enabled
        self._pad.set_alt_mode(enabled)
        self._refresh_mode()

    def _refresh_mode(self) -> None:
        if self._tilt_box.isChecked() != self._tilt:
            self._tilt_box.blockSignals(True)
            self._tilt_box.setChecked(self._tilt)
            self._tilt_box.blockSignals(False)
        self._mode_label.setText(self._mode_text())
        self._mode_label.setProperty("role", "ok" if self._tilt else "muted")
        self._mode_label.style().unpolish(self._mode_label)
        self._mode_label.style().polish(self._mode_label)

    def _mode_text(self) -> str:
        if not self._tilt:
            return "8/2 — вперёд/назад"
        return alt_hint()

    def press_confirm(self) -> None:
        """Нажать «Сохранить F» (для тестов)."""
        self._confirm_button.click()

    def set_busy(self, busy: bool) -> None:
        """Заблокировать управление на время обмена с панелью."""
        self._capture_button.setEnabled(not busy)
        self._confirm_button.setEnabled(not busy)
        self._pad.set_enabled(not busy and self._pose is not None)

    def arrow(self, direction: object) -> QPushButton:
        """Кнопка стрелки (для тестов)."""
        return self._pad.button(direction)  # type: ignore[arg-type]

    def warning_text(self) -> str:
        """Текст предупреждения (пустая строка — предупреждения нет)."""
        return self._warning.text()

    def set_warning(self, text: str) -> None:
        """Показать или скрыть предупреждение под карточкой сдвига."""
        self._warning.setText(text)
        self._warning.setVisible(bool(text))


def _format_step(step: float) -> str:
    return f"{step:g}"


def pose_text(pose: Pose) -> str:
    """Координаты одной строкой для статуса."""
    x = rounded(pose.x, COORD_DECIMALS)
    y = rounded(pose.y, COORD_DECIMALS)
    z = rounded(pose.z, COORD_DECIMALS)
    return f"X {x:.3f} · Y {y:.3f} · Z {z:.3f}"
