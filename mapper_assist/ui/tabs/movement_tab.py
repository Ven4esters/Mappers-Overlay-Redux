from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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

from ...models import MoveSpace
from ..gizmo_widget import GizmoWidget
from ..widgets import make_button, make_label


class MovementTab(QWidget):
    """
    Дополнительные настройки движения (спрятаны в «Инструменты», чтобы не загромождать оверлей):
    оси движения, свой шаг угла, якорь комнаты, пресеты положения
    и поправки направлений на случай инвертированных осей на сервере.
    """

    space_changed = Signal(str)
    rotate_requested = Signal(float)
    angle_step_changed = Signal(float)
    set_anchor_requested = Signal()
    snap_anchor_requested = Signal(float)
    preset_requested = Signal(str)
    invert_changed = Signal(str, bool)
    test_move_requested = Signal()
    test_rotate_requested = Signal()

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.combo_space: QComboBox
        self.spin_angle_step: QDoubleSpinBox
        self.lbl_anchor: QLabel
        self.gizmo: GizmoWidget
        self._invert_boxes: dict[str, QCheckBox] = {}
        self._build()

    # ------------------------------------------------------------------ сборка
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(self._build_space_row())
        layout.addWidget(self._build_angle_box())
        layout.addWidget(self._build_presets_box())
        layout.addWidget(self._build_direction_fix_box())
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

    def _build_angle_box(self) -> QGroupBox:
        box = QGroupBox("Поворот и Якорь комнаты")
        vbox = QVBoxLayout(box)
        vbox.setSpacing(5)

        row = QHBoxLayout()
        row.setSpacing(3)
        for label, deg in (("+90°", 90.0), ("-90°", -90.0), ("180°", 180.0), ("+45°", 45.0), ("-45°", -45.0)):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, d=deg: self.rotate_requested.emit(d))
            row.addWidget(btn)
        vbox.addLayout(row)

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
            btn = QPushButton(title)
            btn.setToolTip(f"Выставить строго {off:+.0f}° относительно базового угла комнаты")
            btn.clicked.connect(lambda _=False, o=off: self.snap_anchor_requested.emit(o))
            snap_row.addWidget(btn)
        vbox.addLayout(snap_row)

        self.gizmo = GizmoWidget()
        vbox.addWidget(self.gizmo)
        return box

    def _build_presets_box(self) -> QGroupBox:
        box = QGroupBox("Положение объекта (сохраняя угол RZ)")
        grid = QGridLayout(box)
        grid.setSpacing(4)
        presets = [
            ("Стоя (0°, 0°)", "upright", 0, 0),
            ("Переворот (бок)", "upside_down_roll", 0, 1),
            ("Переворот (перёд)", "upside_down_pitch", 0, 2),
            ("Плашмя на спину", "flat_back", 1, 0),
            ("Плашмя лицом вниз", "flat_forward", 1, 1),
            ("На правый бок", "flat_right", 1, 2),
        ]
        for txt, key, r, c in presets:
            btn = QPushButton(txt)
            btn.clicked.connect(lambda _=False, k=key: self.preset_requested.emit(k))
            grid.addWidget(btn, r, c)
        return box

    def _build_direction_fix_box(self) -> QGroupBox:
        box = QGroupBox("Если объект уходит не в ту сторону")
        grid = QGridLayout(box)
        grid.setSpacing(4)

        hint = make_label(
            "Включите нужную галочку — направление кнопок сразу поменяется. "
            "Нажмите «Тест», чтобы проверить маленьким шагом.",
            word_wrap=True,
        )
        grid.addWidget(hint, 0, 0, 1, 2)

        options = [
            ("forward", "Вперёд/Назад", 1, 0),
            ("right", "Влево/Вправо", 1, 1),
            ("up", "Вверх/Вниз", 2, 0),
            ("rotate", "Поворот", 2, 1),
        ]
        current = {
            "forward": self._settings.invert_forward,
            "right": self._settings.invert_right,
            "up": self._settings.invert_up,
            "rotate": self._settings.invert_rotate,
        }
        for key, title, row, col in options:
            chk = QCheckBox(title)
            chk.setChecked(bool(current[key]))
            chk.toggled.connect(lambda val, k=key: self.invert_changed.emit(k, val))
            self._invert_boxes[key] = chk
            grid.addWidget(chk, row, col)

        test_row = QHBoxLayout()
        btn_test_move = make_button(
            "Тест: сдвиг 0.05 м",
            "Попробовать сдвинуть объект на 5 см вперёд — сразу видно, в какую сторону он поехал",
        )
        btn_test_move.clicked.connect(lambda: self.test_move_requested.emit())
        btn_test_rotate = make_button(
            "Тест: поворот 15°",
            "Повернуть объект на 15° — проверьте, в ту ли сторону крутится",
        )
        btn_test_rotate.clicked.connect(lambda: self.test_rotate_requested.emit())
        test_row.addWidget(btn_test_move)
        test_row.addWidget(btn_test_rotate)
        grid.addLayout(test_row, 3, 0, 1, 2)
        return box

    # ------------------------------------------------------------------ состояние
    def update_state(self, rz: float, anchor_rz: float, use_anchor_mode: bool) -> None:
        self.gizmo.set_angles(rz, anchor_rz, use_anchor_mode=use_anchor_mode)
        self.lbl_anchor.setText(f"Якорь комнаты: {anchor_rz:+.2f}°")
