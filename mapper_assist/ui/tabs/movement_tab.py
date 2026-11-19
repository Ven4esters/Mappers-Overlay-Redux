from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...models import MoveSpace, format_number
from ..gizmo_widget import GizmoWidget
from ..widgets import make_button, make_label


class MovementTab(QWidget):
    """Вкладка «Движение и Углы»: шаг сдвига, крестовина, повороты, якорь комнаты, пресеты."""

    move_requested = Signal(float, float, float)   # right, forward, up
    rotate_requested = Signal(float)
    set_anchor_requested = Signal()
    snap_anchor_requested = Signal(float)
    preset_requested = Signal(str)
    step_changed = Signal(float)
    angle_step_changed = Signal(float)
    space_changed = Signal(str)

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.spin_step: QDoubleSpinBox
        self.spin_angle_step: QDoubleSpinBox
        self.combo_space: QComboBox
        self.gizmo: GizmoWidget
        self.lbl_anchor: QLabel
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(self._build_space_row())
        layout.addWidget(self._build_step_box())
        layout.addWidget(self._build_pad_box())
        layout.addWidget(self._build_rotate_box())
        layout.addWidget(self._build_presets_box())
        layout.addStretch(1)

    def _build_space_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Оси движения:"))
        self.combo_space = QComboBox()
        self.combo_space.addItem("По углу объекта (горизонт.)", MoveSpace.OBJECT_HORIZONTAL.value)
        self.combo_space.addItem("По якорю комнаты (базовый 0°)", MoveSpace.ANCHOR_HORIZONTAL.value)
        self.combo_space.addItem("3D локальные (с наклоном RX/RY)", MoveSpace.OBJECT_3D.value)
        self.combo_space.addItem("Мировые оси GTA (С/Ю/З/В)", MoveSpace.WORLD.value)
        idx = self.combo_space.findData(self._settings.move_space)
        if idx >= 0:
            self.combo_space.setCurrentIndex(idx)
        self.combo_space.currentIndexChanged.connect(
            lambda _i: self.space_changed.emit(str(self.combo_space.currentData()))
        )
        row.addWidget(self.combo_space, 1)
        return row

    def _build_step_box(self) -> QGroupBox:
        box = QGroupBox("Шаг сдвига (метры)")
        vbox = QVBoxLayout(box)
        vbox.setSpacing(4)

        input_row = QHBoxLayout()
        self.spin_step = QDoubleSpinBox()
        self.spin_step.setRange(0.0005, 500.0)
        self.spin_step.setDecimals(4)
        self.spin_step.setSingleStep(0.05)
        self.spin_step.setSuffix(" м")
        self.spin_step.setValue(self._settings.step)
        self.spin_step.valueChanged.connect(lambda v: self.step_changed.emit(float(v)))
        input_row.addWidget(self.spin_step, 1)

        btn_half = QPushButton("÷2")
        btn_half.setMaximumWidth(38)
        btn_half.clicked.connect(lambda: self.spin_step.setValue(max(0.0005, self.spin_step.value() / 2.0)))
        input_row.addWidget(btn_half)

        btn_double = QPushButton("×2")
        btn_double.setMaximumWidth(38)
        btn_double.clicked.connect(lambda: self.spin_step.setValue(min(500.0, self.spin_step.value() * 2.0)))
        input_row.addWidget(btn_double)
        vbox.addLayout(input_row)

        presets = QGridLayout()
        presets.setSpacing(3)
        for i, val in enumerate(self._settings.step_presets[:8]):
            b = QPushButton(format_number(val, 4))
            b.clicked.connect(lambda _=False, v=val: self.spin_step.setValue(v))
            presets.addWidget(b, i // 4, i % 4)
        vbox.addLayout(presets)
        return box

    def _build_pad_box(self) -> QGroupBox:
        box = QGroupBox("Точное перемещение")
        row = QHBoxLayout(box)
        row.setSpacing(8)

        pad = QGridLayout()
        pad.setSpacing(4)

        btn_fw = make_button("▲ Вперёд", "Сдвинуть по направлению «вперёд» на один шаг")
        btn_fw.setObjectName("btnMovePrimary")
        btn_fw.clicked.connect(lambda: self.move_requested.emit(0.0, 1.0, 0.0))

        btn_bk = make_button("▼ Назад")
        btn_bk.setObjectName("btnMovePrimary")
        btn_bk.clicked.connect(lambda: self.move_requested.emit(0.0, -1.0, 0.0))

        btn_lt = make_button("◄ Влево")
        btn_lt.setObjectName("btnMovePrimary")
        btn_lt.clicked.connect(lambda: self.move_requested.emit(-1.0, 0.0, 0.0))

        btn_rt = make_button("► Вправо")
        btn_rt.setObjectName("btnMovePrimary")
        btn_rt.clicked.connect(lambda: self.move_requested.emit(1.0, 0.0, 0.0))

        btn_up = make_button("▲ Верх +Z", "Поднять объект по мировой оси Z (всегда вверх)")
        btn_up.clicked.connect(lambda: self.move_requested.emit(0.0, 0.0, 1.0))

        btn_dn = make_button("▼ Низ -Z", "Опустить объект по мировой оси Z (всегда вниз)")
        btn_dn.clicked.connect(lambda: self.move_requested.emit(0.0, 0.0, -1.0))

        pad.addWidget(btn_fw, 0, 1)
        pad.addWidget(btn_lt, 1, 0)
        pad.addWidget(btn_rt, 1, 2)
        pad.addWidget(btn_bk, 2, 1)
        pad.addWidget(btn_up, 0, 3)
        pad.addWidget(btn_dn, 2, 3)
        row.addLayout(pad, 1)

        self.gizmo = GizmoWidget()
        row.addWidget(self.gizmo)
        return box

    def _build_rotate_box(self) -> QGroupBox:
        box = QGroupBox("Поворот вокруг Z и Якорь комнаты")
        vbox = QVBoxLayout(box)
        vbox.setSpacing(5)

        rel_row = QHBoxLayout()
        rel_row.setSpacing(3)
        for label, deg in (("+90°", 90.0), ("-90°", -90.0), ("180°", 180.0), ("+45°", 45.0), ("-45°", -45.0)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, d=deg: self.rotate_requested.emit(d))
            rel_row.addWidget(b)
        vbox.addLayout(rel_row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Свой шаг угла:"))
        self.spin_angle_step = QDoubleSpinBox()
        self.spin_angle_step.setRange(0.05, 180.0)
        self.spin_angle_step.setDecimals(2)
        self.spin_angle_step.setSuffix("°")
        self.spin_angle_step.setValue(self._settings.angle_step)
        self.spin_angle_step.valueChanged.connect(lambda v: self.angle_step_changed.emit(float(v)))
        custom_row.addWidget(self.spin_angle_step, 1)

        btn_plus = QPushButton("+Шаг°")
        btn_plus.clicked.connect(lambda: self.rotate_requested.emit(self.spin_angle_step.value()))
        btn_minus = QPushButton("-Шаг°")
        btn_minus.clicked.connect(lambda: self.rotate_requested.emit(-self.spin_angle_step.value()))
        custom_row.addWidget(btn_plus)
        custom_row.addWidget(btn_minus)
        vbox.addLayout(custom_row)

        anchor_row = QHBoxLayout()
        self.lbl_anchor = make_label("")
        anchor_row.addWidget(self.lbl_anchor, 1)
        btn_set_anchor = make_button(
            "Взять из объекта",
            "Запомнить текущий угол RZ объекта как базовый 0° комнаты",
        )
        btn_set_anchor.clicked.connect(lambda: self.set_anchor_requested.emit())
        anchor_row.addWidget(btn_set_anchor)
        vbox.addLayout(anchor_row)

        snap_row = QHBoxLayout()
        snap_row.setSpacing(3)
        for title, off in (("0° комн.", 0.0), ("+90°", 90.0), ("-90°", -90.0), ("180°", 180.0), ("+45°", 45.0), ("-45°", -45.0)):
            b = QPushButton(title)
            b.setToolTip(f"Выставить строго {off:+.0f}° относительно базового угла комнаты")
            b.clicked.connect(lambda _=False, o=off: self.snap_anchor_requested.emit(o))
            snap_row.addWidget(b)
        vbox.addLayout(snap_row)
        return box

    def _build_presets_box(self) -> QGroupBox:
        box = QGroupBox("Положение объекта (сохраняя угол RZ)")
        grid = QGridLayout(box)
        grid.setSpacing(4)
        presets = [
            ("Стоя (0°, 0°)", "upright", 0, 0),
            ("Вверх ногами (Бок)", "upside_down_roll", 0, 1),
            ("Вверх ногами (Перёд)", "upside_down_pitch", 0, 2),
            ("Плашмя на спину", "flat_back", 1, 0),
            ("Плашмя лицом вниз", "flat_forward", 1, 1),
            ("На правый бок", "flat_right", 1, 2),
        ]
        for txt, key, r, c in presets:
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, k=key: self.preset_requested.emit(k))
            grid.addWidget(b, r, c)
        return box

    # ------------------------------------------------------------------ state
    def update_state(self, rz: float, anchor_rz: float, use_anchor_mode: bool) -> None:
        self.gizmo.set_angles(rz, anchor_rz, use_anchor_mode=use_anchor_mode)
        self.lbl_anchor.setText(f"Якорь комнаты: {anchor_rz:+.2f}°")

    def set_step_value(self, value: float) -> None:
        self.spin_step.setValue(value)
