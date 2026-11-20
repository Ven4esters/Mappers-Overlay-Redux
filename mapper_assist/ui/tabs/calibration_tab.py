from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...models import CALIBRATION_LABELS, CALIBRATION_TARGETS, CalibrationProfile
from ..widgets import make_button, make_label


class CalibrationTab(QWidget):
    """Вкладка «Калибровка»: экранные точки 6 полей + нейтральная точка, режимы захвата."""

    wizard_requested = Signal()
    single_requested = Signal(str)
    fast_capture_toggled = Signal(bool)
    unfocus_toggled = Signal(bool)
    safe_verify_toggled = Signal(bool)
    max_jump_changed = Signal(float)

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.calib_coord_labels: dict[str, QLabel] = {}
        self.btn_wizard_all: QPushButton
        self.chk_fast_capture: QCheckBox
        self.chk_unfocus_paste: QCheckBox
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        info = make_label(
            "Настройте координаты 6 полей левой панели LSP и 1 нейтральную точку мимо полей "
            "(пустое место панели или экрана, куда кликается ЛКМ перед нажатием Enter).",
            word_wrap=True,
        )
        layout.addWidget(info)

        self.btn_wizard_all = make_button("Пошаговая калибровка всех 7 точек")
        self.btn_wizard_all.setObjectName("btnWarn")
        self.btn_wizard_all.clicked.connect(lambda: self.wizard_requested.emit())
        layout.addWidget(self.btn_wizard_all)

        pts_box = QGroupBox("Точки экрана")
        grid = QGridLayout(pts_box)
        grid.setSpacing(4)

        for row, target in enumerate(CALIBRATION_TARGETS):
            title = QLabel(CALIBRATION_LABELS[target])
            coord_lbl = QLabel("не задано")
            coord_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.calib_coord_labels[target] = coord_lbl

            btn_one = QPushButton("Задать")
            btn_one.setMaximumWidth(68)
            btn_one.clicked.connect(lambda _=False, t=target: self.single_requested.emit(t))

            grid.addWidget(title, row, 0)
            grid.addWidget(coord_lbl, row, 1)
            grid.addWidget(btn_one, row, 2)

        layout.addWidget(pts_box)

        self.chk_fast_capture = QCheckBox("Турбо-захват: читать только X, Y, Z, RZ (считать RX=0, RY=0)")
        self.chk_fast_capture.setChecked(self._settings.fast_capture_skip_tilt)
        self.chk_fast_capture.toggled.connect(self.fast_capture_toggled.emit)
        layout.addWidget(self.chk_fast_capture)

        self.chk_unfocus_paste = QCheckBox("Снимать фокус с поля (клик мимо без Enter), когда авто-сохранение выкл.")
        self.chk_unfocus_paste.setChecked(self._settings.unfocus_after_paste)
        self.chk_unfocus_paste.toggled.connect(self.unfocus_toggled.emit)
        layout.addWidget(self.chk_unfocus_paste)

        safety_box = QGroupBox("Защита от «улёта» объекта")
        safety_v = QVBoxLayout(safety_box)
        safety_v.setSpacing(4)

        self.chk_safe_verify = QCheckBox("Проверять поля после вставки (рекомендуется)")
        self.chk_safe_verify.setToolTip(
            "После Ctrl+V координаты перечитываются и сравниваются с ожидаемыми. "
            "Если панель не приняла значение, операция отменяется, а объект остаётся на месте."
        )
        self.chk_safe_verify.setChecked(self._settings.safe_write_verify)
        self.chk_safe_verify.toggled.connect(self.safe_verify_toggled.emit)
        safety_v.addWidget(self.chk_safe_verify)

        jump_row = QHBoxLayout()
        jump_row.addWidget(QLabel("Макс. скачок за раз:"))
        self.spin_max_jump = QDoubleSpinBox()
        self.spin_max_jump.setRange(1.0, 500.0)
        self.spin_max_jump.setDecimals(1)
        self.spin_max_jump.setSuffix(" м")
        self.spin_max_jump.setValue(float(self._settings.max_jump))
        self.spin_max_jump.setToolTip(
            "Если новые координаты отличаются от прочитанных из игры больше чем на это значение, "
            "ввод блокируется — так сбой вставки не унесёт объект на другой конец карты."
        )
        self.spin_max_jump.valueChanged.connect(lambda v: self.max_jump_changed.emit(float(v)))
        jump_row.addWidget(self.spin_max_jump, 1)
        safety_v.addLayout(jump_row)
        layout.addWidget(safety_box)

        layout.addStretch(1)

    def refresh_points(self, calibration: CalibrationProfile) -> None:
        for target, lbl in self.calib_coord_labels.items():
            pt = calibration.get_point(target)
            if pt is None:
                lbl.setText("не задано")
                lbl.setStyleSheet("color: #f59e0b;")
            else:
                lbl.setText(f"{pt.x}, {pt.y}")
                lbl.setStyleSheet("color: #4ade80;")

    def set_hotkey_title(self, hotkey_name: str) -> None:
        self.btn_wizard_all.setText(f"Пошаговая калибровка всех 7 точек (клавиша {hotkey_name or 'F9'})")
