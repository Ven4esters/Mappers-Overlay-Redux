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
    slope_directions,
    validate_step,
)
from map_overlay.domain.pose import Pose
from map_overlay.errors import ValidationError
from map_overlay.ui.widgets import Card, DirectionPad, PoseGrid, button, label

STEP_PRESETS: Final[tuple[str, ...]] = ("0.1", "0.25", "0.5", "1", "2", "5", "10")
STEP_DECIMALS: Final = 3


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

        pose_card = Card("Координаты и углы")
        self._grid = PoseGrid(self)
        pose_card.add(self._grid)
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
        pose_card.add_layout(row)
        layout.addWidget(pose_card)

        move_card = Card("Сдвиг предмета")
        self._pad = DirectionPad(self)
        self._pad.direction_clicked.connect(self._request_move)
        move_card.add(self._pad)

        step_row = QHBoxLayout()
        step_row.setSpacing(8)
        step_row.addWidget(label("Шаг", widget_role="muted"))
        self._step_combo = QComboBox(self)
        self._step_combo.setEditable(True)
        self._step_combo.addItems(STEP_PRESETS)
        self._step_combo.setCurrentText(_format_step(default_step))
        self._step_combo.setValidator(QDoubleValidator(MIN_STEP, MAX_STEP, STEP_DECIMALS, self))
        self._step_combo.setLocale(QLocale.c())
        self._step_combo.setMinimumWidth(96)
        self._step_combo.editTextChanged.connect(self._sync_step_text)
        step_row.addWidget(self._step_combo)
        step_row.addWidget(label("м", widget_role="muted"))
        step_row.addStretch(1)
        move_card.add_layout(step_row)

        mode_row = QHBoxLayout()
        self._tilt_box = QCheckBox("Режим наклона", self)
        self._tilt_box.setToolTip(
            "Шаги идут по плоскости предмета. То же самое делает одно нажатие Alt."
        )
        self._tilt_box.toggled.connect(self.tilt_toggled.emit)
        mode_row.addWidget(self._tilt_box)
        mode_row.addStretch(1)
        self._mode_label = label("по плоскости", widget_role="muted")
        self._mode_label.setWordWrap(False)
        mode_row.addWidget(self._mode_label)
        move_card.add_layout(mode_row)

        move_card.add(
            label(
                "Одна стрелка — один шаг; те же действия есть на Numpad. Зажмите клавишу — "
                "шаг повторяется сразу за предыдущим, отпустите — движение останавливается.",
                widget_role="muted",
            )
        )
        move_card.add(
            label(
                "Одно нажатие Alt включает режим наклона: шаги идут по плоскости предмета, "
                "и поднимается та сторона, вокруг которой наклон (при RX — «влево-вправо», "
                "при RY — «вперёд-назад»). Ещё одно нажатие — выключить. Держать Alt не "
                "нужно: пока он зажат, игра не применяет правки панели.",
                widget_role="muted",
            )
        )
        layout.addWidget(move_card)

        self._warning = label("", widget_role="warn")
        self._warning.hide()
        layout.addWidget(self._warning)
        layout.addStretch(1)

        self._pad.set_enabled(False)
        self._sync_step_text()

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
        """Показать, идут ли шаги по наклону RX."""
        self._tilt = enabled
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
            return "по плоскости"
        if self._pose is None:
            return "по наклону"
        compass = _compass_text(self._pose)
        return f"по наклону{compass}"

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


def _compass_text(pose: Pose) -> str:
    """Куда идти вверх и вниз по плоскости предмета."""
    up, down = slope_directions(pose)
    if up is None and down is None:
        return ""
    parts = []
    if up is not None:
        parts.append(f"вверх {up.glyph}")
    if down is not None:
        parts.append(f"вниз {down.glyph}")
    return " · " + " · ".join(parts)


def _format_step(step: float) -> str:
    return f"{step:g}"


def pose_text(pose: Pose) -> str:
    """Координаты одной строкой для статуса."""
    x = rounded(pose.x, COORD_DECIMALS)
    y = rounded(pose.y, COORD_DECIMALS)
    z = rounded(pose.z, COORD_DECIMALS)
    return f"X {x:.3f} · Y {y:.3f} · Z {z:.3f}"
