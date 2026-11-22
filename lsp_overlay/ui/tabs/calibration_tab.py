"""Вкладка «Калибровка»: точки полей и «пустое место» для клавиши F."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.config import Calibration, Point
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.ui.widgets import make_button, make_label

COUNTDOWN_SECONDS = 3
FIELD_TITLES: tuple[tuple[FieldKey, str], ...] = (
    (FieldKey.X, "Поле X (координата)"),
    (FieldKey.Y, "Поле Y (координата)"),
    (FieldKey.Z, "Поле Z (высота)"),
    (FieldKey.RX, "Поле RX (наклон)"),
    (FieldKey.RY, "Поле RY (крен)"),
    (FieldKey.RZ, "Поле RZ (поворот)"),
)
PLACEHOLDER_TITLE = "Пустое место панели (клик перед клавишей F)"


class CalibrationTab(QWidget):
    """Задаёт точки экрана: 6 полей + точка подтверждения."""

    calibration_changed = Signal(object)
    status_message = Signal(str, str)

    def __init__(self, calibration: Calibration, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._calibration = calibration
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._seconds_left = 0
        self._pending_target: FieldKey | None = None
        self._pending_placeholder = False
        self._labels: dict[FieldKey, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(
            make_label(
                "Нажмите «Задать», за 3 секунды наведите курсор на нужное поле панели LSP "
                "и не двигайте мышью.",
                muted=True,
                wrap=True,
            )
        )
        layout.addWidget(self._build_fields_group())
        layout.addWidget(self._build_placeholder_group())
        layout.addStretch(1)
        self.refresh()

    def _build_fields_group(self) -> QGroupBox:
        group = QGroupBox("Точки полей")
        grid = QGridLayout(group)
        grid.setVerticalSpacing(4)
        for row, (key, title) in enumerate(FIELD_TITLES):
            grid.addWidget(make_label(title), row, 0)
            label = make_label("—", muted=True)
            grid.addWidget(label, row, 1)
            button = make_button("Задать", f"Задать точку поля {key.value.upper()}")
            button.clicked.connect(lambda _checked=False, target=key: self._start_capture(target))
            grid.addWidget(button, row, 2)
            self._labels[key] = label
        return group

    def _build_placeholder_group(self) -> QGroupBox:
        group = QGroupBox("Подтверждение ввода")
        row = QHBoxLayout(group)
        self.lbl_placeholder = make_label("—", muted=True)
        row.addWidget(self.lbl_placeholder, 1)
        self.btn_placeholder = make_button("Задать", "Задать «пустое место» панели")
        self.btn_placeholder.clicked.connect(self._start_placeholder_capture)
        row.addWidget(self.btn_placeholder)
        self.btn_reset = make_button("Сбросить всё", "Забыть все точки калибровки")
        self.btn_reset.clicked.connect(self._reset)
        row.addWidget(self.btn_reset)
        return group

    # ------------------------------------------------------------------ захват
    def _start_capture(self, key: FieldKey) -> None:
        self._pending_target = key
        self._pending_placeholder = False
        self._start_countdown(f"поля {key.value.upper()}")

    def _start_placeholder_capture(self) -> None:
        self._pending_target = None
        self._pending_placeholder = True
        self._start_countdown("пустого места")

    def _start_countdown(self, target_title: str) -> None:
        self._seconds_left = COUNTDOWN_SECONDS
        self.status_message.emit(
            f"Наведите курсор на {target_title}: осталось {self._seconds_left} с", "info"
        )
        self._timer.start(1000)

    def _tick(self) -> None:
        self._seconds_left -= 1
        if self._seconds_left > 0:
            self.status_message.emit(f"Осталось {self._seconds_left} с", "info")
            self._timer.start(1000)
            return
        self._commit_capture()

    def _commit_capture(self) -> None:
        cursor = QCursor.pos()
        point = Point(x=cursor.x(), y=cursor.y())
        if self._pending_placeholder:
            self._calibration = self._calibration.with_placeholder(point)
        elif self._pending_target is not None:
            self._calibration = self._calibration.with_point(self._pending_target, point)
        self._pending_placeholder = False
        self._pending_target = None
        self.refresh()
        self.calibration_changed.emit(self._calibration)
        state = " готово" if self._calibration.is_complete else " — не хватает точек"
        self.status_message.emit(f"Точка {point.x}, {point.y} записана{state}", "success")

    def _reset(self) -> None:
        self._calibration = Calibration.empty()
        self.refresh()
        self.calibration_changed.emit(self._calibration)
        self.status_message.emit("Калибровка сброшена", "info")

    # ------------------------------------------------------------------- вывод
    def refresh(self) -> None:
        """Обновляет координаты точек на экране."""
        for key, label in self._labels.items():
            point = self._calibration.fields.get(key)
            label.setText(f"{point.x}, {point.y}" if point else "—")
        placeholder = self._calibration.placeholder
        self.lbl_placeholder.setText(f"{placeholder.x}, {placeholder.y}" if placeholder else "—")

    @property
    def calibration(self) -> Calibration:
        """Текущая калибровка."""
        return self._calibration

    def set_calibration(self, calibration: Calibration) -> None:
        """Подставляет калибровку из настроек."""
        self._calibration = calibration
        self.refresh()
