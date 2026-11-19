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

from ...math3d import TwoPointMeasurement
from ...models import Transform, format_number
from ..widgets import make_button, make_label


class JoinTab(QWidget):
    """Вкладка «Стыковка и Линейка»: размер секции, конвейер секций, поворот за край, линейка A→B."""

    prop_size_changed = Signal(float)
    saved_size_picked = Signal(float)
    save_size_requested = Signal()
    reference_save_requested = Signal()
    advance_reference_changed = Signal(bool)
    align_requested = Signal()
    join_requested = Signal(str, float)       # direction, turn_deg
    edge_rotate_requested = Signal(float, str)  # delta_deg, edge
    point_a_requested = Signal()
    point_b_requested = Signal()
    ruler_anchor_requested = Signal()
    ruler_mid_requested = Signal()

    def __init__(self, settings, advance_reference: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build()
        self.chk_advance_ref.setChecked(advance_reference)
        self.reload_saved_sizes()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(7)
        layout.addWidget(self._build_size_box())
        layout.addWidget(self._build_conveyor_box())
        layout.addWidget(self._build_ruler_box())
        layout.addStretch(1)

    def _build_size_box(self) -> QGroupBox:
        box = QGroupBox("Размер секции пропа (стена / забор / плита)")
        vbox = QVBoxLayout(box)

        row = QHBoxLayout()
        self.spin_prop_size = QDoubleSpinBox()
        self.spin_prop_size.setRange(0.01, 500.0)
        self.spin_prop_size.setDecimals(4)
        self.spin_prop_size.setSuffix(" м")
        self.spin_prop_size.setValue(self._settings.prop_size)
        self.spin_prop_size.valueChanged.connect(lambda v: self.prop_size_changed.emit(float(v)))
        row.addWidget(self.spin_prop_size, 1)

        self.btn_to_step = make_button("→ В шаг", "Скопировать этот размер в основной шаг сдвига")
        row.addWidget(self.btn_to_step)
        vbox.addLayout(row)

        saved_row = QHBoxLayout()
        self.combo_saved_sizes = QComboBox()
        self.combo_saved_sizes.activated.connect(self._on_saved_size_activated)
        saved_row.addWidget(self.combo_saved_sizes, 1)

        btn_save = make_button("+ Сохранить", "Сохранить размер с именем в список заготовок")
        btn_save.clicked.connect(lambda: self.save_size_requested.emit())
        saved_row.addWidget(btn_save)
        vbox.addLayout(saved_row)
        return box

    def _build_conveyor_box(self) -> QGroupBox:
        box = QGroupBox("Конвейер секций и Г-образные углы")
        vbox = QVBoxLayout(box)
        vbox.setSpacing(5)

        ref_row = QHBoxLayout()
        self.lbl_ref_state = make_label("Эталон: не задан")
        ref_row.addWidget(self.lbl_ref_state, 1)
        btn_ref = make_button("Запомнить эталон", "Запомнить координаты и угол текущего пропа как эталон стыковки")
        btn_ref.clicked.connect(lambda: self.reference_save_requested.emit())
        ref_row.addWidget(btn_ref)
        vbox.addLayout(ref_row)

        self.chk_advance_ref = QCheckBox("Авто-смещать эталон на каждую новую секцию")
        self.chk_advance_ref.toggled.connect(self.advance_reference_changed.emit)
        vbox.addWidget(self.chk_advance_ref)

        btn_clone = make_button("Подтянуть новый проп точно в координаты эталона")
        btn_clone.clicked.connect(lambda: self.align_requested.emit())
        vbox.addWidget(btn_clone)

        grid = QGridLayout()
        grid.setSpacing(4)
        join_actions = [
            ("Стык Вправо (+X)", "right", 0.0, 0, 0),
            ("Стык Влево (-X)", "left", 0.0, 0, 1),
            ("Стык Вперёд (+Y)", "forward", 0.0, 1, 0),
            ("Стык Назад (-Y)", "back", 0.0, 1, 1),
            ("Угол +90° от правого края", "right", 90.0, 2, 0),
            ("Угол -90° от правого края", "right", -90.0, 2, 1),
        ]
        for txt, direction, turn, r, c in join_actions:
            b = QPushButton(txt)
            b.clicked.connect(
                lambda _=False, d=direction, t=turn: self.join_requested.emit(d, t)
            )
            grid.addWidget(b, r, c)
        vbox.addLayout(grid)

        edge_row = QHBoxLayout()
        edge_row.addWidget(QLabel("Крутить этот проп за край:"))
        for txt, edge, deg in (("Лев +90°", "left", 90.0), ("Прав +90°", "right", 90.0), ("Прав -90°", "right", -90.0)):
            b = QPushButton(txt)
            b.setToolTip("Поворачивает текущий объект вокруг его края, пересчитывая X и Y")
            b.clicked.connect(
                lambda _=False, e=edge, d=deg: self.edge_rotate_requested.emit(d, e)
            )
            edge_row.addWidget(b)
        vbox.addLayout(edge_row)
        return box

    def _build_ruler_box(self) -> QGroupBox:
        box = QGroupBox("Линейка по двум точкам (A → B)")
        vbox = QVBoxLayout(box)
        vbox.setSpacing(5)

        pts_row = QHBoxLayout()
        btn_a = QPushButton("Записать точку A")
        btn_a.clicked.connect(lambda: self.point_a_requested.emit())
        btn_b = QPushButton("Записать точку B")
        btn_b.clicked.connect(lambda: self.point_b_requested.emit())
        pts_row.addWidget(btn_a)
        pts_row.addWidget(btn_b)
        vbox.addLayout(pts_row)

        self.lbl_ruler_info = make_label(
            "Поставьте проп в начало стены (A) и конец стены (B), чтобы узнать точный угол и длину.",
            word_wrap=True,
        )
        vbox.addWidget(self.lbl_ruler_info)

        btns = QHBoxLayout()
        btn_anchor = QPushButton("Угол A→B в Якорь")
        btn_anchor.clicked.connect(lambda: self.ruler_anchor_requested.emit())
        btn_mid = make_button("В центр A–B", "Переместить текущий объект ровно посередине между A и B")
        btn_mid.clicked.connect(lambda: self.ruler_mid_requested.emit())
        btns.addWidget(btn_anchor)
        btns.addWidget(btn_mid)
        vbox.addLayout(btns)
        return box

    # ------------------------------------------------------------------ state
    def _on_saved_size_activated(self, index: int) -> None:
        data = self.combo_saved_sizes.itemData(index)
        if data is not None:
            self.saved_size_picked.emit(float(data))

    def reload_saved_sizes(self) -> None:
        self.combo_saved_sizes.clear()
        self.combo_saved_sizes.addItem("Выбрать сохранённый размер...", None)
        for item in self._settings.saved_prop_sizes:
            name = item.get("name", "Проп")
            size = float(item.get("size", 1.0))
            self.combo_saved_sizes.addItem(f"{name} ({format_number(size, 4)} м)", size)

    def set_reference_state(self, ref: Transform | None) -> None:
        if ref is None:
            self.lbl_ref_state.setText("Эталон: не задан")
        else:
            self.lbl_ref_state.setText(
                f"Эталон: ({ref.x:.2f}, {ref.y:.2f}, {ref.z:.2f}) | RZ {ref.rz:+.1f}°"
            )

    def show_measurement(self, meas: TwoPointMeasurement | None) -> None:
        if meas is None:
            return
        self.lbl_ruler_info.setText(
            f"Длина 2D: {meas.distance_2d:.4f} м | 3D: {meas.distance_3d:.4f} м | dZ: {meas.dz:+.4f} м\n"
            f"Угол стены (ось X): {meas.rz_along_x:+.3f}° | Взгляд A→B (ось Y): {meas.rz_look_along_y:+.3f}°"
        )
