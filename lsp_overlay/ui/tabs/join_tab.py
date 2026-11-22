"""Вкладка «Стык»: второй предмет встаёт к первому точно, без щели и наложения."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.domain.catalog import Catalog, ObjectSpec
from lsp_overlay.domain.errors import DomainError
from lsp_overlay.domain.formatting import format_length
from lsp_overlay.domain.join import (
    CORNER_ANGLE,
    MAX_JOIN_ANGLE,
    MIN_JOIN_ANGLE,
    MITRE_ANGLE,
    AcrossField,
    JoinRequest,
    JoinScheme,
    JoinSide,
    join_pose,
    local_offset,
)
from lsp_overlay.domain.pose import Pose
from lsp_overlay.ui.widgets import make_button, make_label, make_number_editor

EMPTY_TEXT = "—"
HINT = (
    "Стык считается в плане: «A» — предмет, который уже стоит, «B» — который приставляем. "
    "Буква Г: торец B к торцу A, внешние грани заподлицо (90°, 45° или свой угол). "
    "Буква Т: торец B упирается в бок A. Координаты B пишутся в панель сразу, без F. "
    "«Поперёк» — какой габарит считать глубиной детали в стыке."
)


class JoinTab(QWidget):
    """Стык двух предметов из таблицы: угол, сторона и установка B."""

    place_requested = Signal()
    swap_requested = Signal()
    status_message = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = Catalog()
        self._pose = Pose()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self._build_objects())
        layout.addWidget(self._build_geometry())
        layout.addWidget(self._build_result())
        layout.addWidget(self._build_actions())
        layout.addStretch(1)
        layout.addWidget(make_label(HINT, muted=True, wrap=True))

    # ------------------------------------------------------------------ сборка
    def _build_objects(self) -> QGroupBox:
        group = QGroupBox("Предметы")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self.combo_first = QComboBox()
        self.combo_first.setToolTip("Предмет, который уже стоит в игре (от него считаем стык)")
        self.combo_second = QComboBox()
        self.combo_second.setToolTip("Предмет, который приставляем вторым")
        for combo in (self.combo_first, self.combo_second):
            combo.currentIndexChanged.connect(self._on_selection_changed)
        for row, (title, combo) in enumerate(
            (("Первый (A)", self.combo_first), ("Второй (B)", self.combo_second))
        ):
            grid.addWidget(make_label(title, muted=True), row, 0)
            grid.addWidget(combo, row, 1)
        grid.addWidget(
            make_label(
                "Габариты берутся из «Объектов»: не мерили — стык не посчитать.",
                muted=True,
                wrap=True,
            ),
            2,
            0,
            1,
            2,
        )
        return group

    def _build_geometry(self) -> QGroupBox:
        group = QGroupBox("Схема и угол")
        column = QVBoxLayout(group)
        column.setSpacing(4)
        schemes = QHBoxLayout()
        schemes.setSpacing(8)
        self.radio_corner = QRadioButton(JoinScheme.CORNER.label)
        self.radio_corner.setChecked(True)
        self.radio_corner.setToolTip(
            "Торец B приставляется к торцу A, внешние грани продолжают друг друга"
        )
        self.radio_tee = QRadioButton(JoinScheme.TEE.label)
        self.radio_tee.setToolTip("Торец B упирается в боковую грань A — получается буква Т")
        for button in (self.radio_corner, self.radio_tee):
            button.toggled.connect(self._on_geometry_changed)
            schemes.addWidget(button, 1)
        column.addLayout(schemes)

        angles = QHBoxLayout()
        angles.setSpacing(4)
        angles.addWidget(make_label("Угол", muted=True))
        self.spin_angle = make_number_editor(1, minimum=MIN_JOIN_ANGLE, maximum=MAX_JOIN_ANGLE)
        self.spin_angle.setValue(CORNER_ANGLE)
        self.spin_angle.setSuffix("°")
        self.spin_angle.setSingleStep(5.0)
        self.spin_angle.valueChanged.connect(self._on_angle_value_changed)
        angles.addWidget(self.spin_angle, 1)
        self.btn_90 = make_button(
            "90°", "Прямой стык — буква Г", object_name="stepButton", checkable=True
        )
        self.btn_45 = make_button(
            "45°", "Стык под 45° — фаска на угол", object_name="stepButton", checkable=True
        )
        self.btn_90.setChecked(True)
        self.btn_90.clicked.connect(lambda: self._set_angle(CORNER_ANGLE))
        self.btn_45.clicked.connect(lambda: self._set_angle(MITRE_ANGLE))
        for preset_button in (self.btn_90, self.btn_45):
            angles.addWidget(preset_button)
        column.addLayout(angles)

        across_row = QHBoxLayout()
        across_row.setSpacing(4)
        across_row.addWidget(make_label("Поперёк", muted=True))
        self.combo_across = QComboBox()
        self.combo_across.setToolTip(
            "Ширина — обычный поперечный габарит; толщина — если стыкуете плиты по толщине"
        )
        for field in AcrossField:
            self.combo_across.addItem(field.label, field.value)
        self.combo_across.currentIndexChanged.connect(self._on_geometry_changed)
        across_row.addWidget(self.combo_across, 1)
        self.lbl_across = make_label(EMPTY_TEXT, muted=True)
        across_row.addWidget(self.lbl_across)
        column.addLayout(across_row)

        sides = QHBoxLayout()
        sides.setSpacing(8)
        self.radio_left = QRadioButton(JoinSide.LEFT.label)
        self.radio_right = QRadioButton(JoinSide.RIGHT.label)
        self.radio_right.setChecked(True)
        for button in (self.radio_left, self.radio_right):
            button.toggled.connect(self._on_geometry_changed)
            sides.addWidget(button, 1)
        column.addLayout(sides)
        return group

    def _build_result(self) -> QGroupBox:
        group = QGroupBox("Куда встанет B")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)
        self.lbl_base = make_label(EMPTY_TEXT, muted=True, wrap=True)
        self._value_labels: dict[str, QLabel] = {}
        for row, (key, title) in enumerate((("x", "X"), ("y", "Y"), ("rz", "RZ"))):
            grid.addWidget(make_label(title, muted=True), row, 0)
            value = QLabel(EMPTY_TEXT)
            value.setObjectName("measureValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._value_labels[key] = value
            grid.addWidget(value, row, 1)
        self.lbl_shift = make_label(EMPTY_TEXT, muted=True, wrap=True)
        grid.addWidget(self.lbl_shift, len(self._value_labels), 0, 1, 2)
        grid.addWidget(self.lbl_base, len(self._value_labels) + 1, 0, 1, 2)
        return group

    def _build_actions(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        self.btn_place = make_button(
            "Поставить B",
            "Записать координаты второго предмета в панель (без подтверждения F)",
            object_name="primaryButton",
        )
        self.btn_place.clicked.connect(self.place_requested.emit)
        self.btn_swap = make_button("A ↔ B", "Продолжить стык от второго предмета")
        self.btn_swap.clicked.connect(self.swap_requested.emit)
        column.addWidget(self.btn_place)
        column.addWidget(self.btn_swap)
        return holder

    # ------------------------------------------------------------------ события
    def _set_angle(self, angle: float) -> None:
        self.spin_angle.setValue(angle)

    def _on_angle_value_changed(self, value: float) -> None:
        self.btn_90.setChecked(abs(value - CORNER_ANGLE) < 0.05)
        self.btn_45.setChecked(abs(value - MITRE_ANGLE) < 0.05)
        self._update_preview()

    def _on_geometry_changed(self, _checked: bool = False) -> None:
        is_tee = self.radio_tee.isChecked()
        self.spin_angle.setEnabled(not is_tee)
        self.btn_90.setEnabled(not is_tee)
        self.btn_45.setEnabled(not is_tee)
        self._update_preview()

    def _on_selection_changed(self) -> None:
        self._update_preview()

    # ------------------------------------------------------------------- запрос
    def request(self) -> JoinRequest:
        """Что и под каким углом приставляем."""
        scheme = JoinScheme.TEE if self.radio_tee.isChecked() else JoinScheme.CORNER
        side = JoinSide.LEFT if self.radio_left.isChecked() else JoinSide.RIGHT
        return JoinRequest(
            scheme=scheme,
            angle=self.spin_angle.value(),
            side=side,
            across=AcrossField(self.combo_across.currentData()),
        )

    def selected_specs(self) -> tuple[ObjectSpec | None, ObjectSpec | None]:
        """Предметы A и B из списков."""
        return self._selected(self.combo_first), self._selected(self.combo_second)

    @staticmethod
    def _selected(combo: QComboBox) -> ObjectSpec | None:
        data = combo.currentData()
        return data if isinstance(data, ObjectSpec) else None

    # ------------------------------------------------------------------- вывод
    def show_catalog(self, catalog: Catalog) -> None:
        """Обновляет списки предметов, сохраняя выбранные названия."""
        first = self._selected(self.combo_first)
        second = self._selected(self.combo_second)
        self._catalog = catalog
        for combo, previous in ((self.combo_first, first), (self.combo_second, second)):
            combo.blockSignals(True)
            combo.clear()
            for spec in catalog.objects:
                combo.addItem(f"{spec.name} — {format_length(spec.length, 2)} м", spec)
            self._select_name(combo, previous.name if previous is not None else "")
            if combo.count() and combo.currentIndex() < 0:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
        if self._selected(self.combo_second) is None and self.combo_first.count():
            self.combo_second.blockSignals(True)
            self.combo_second.setCurrentIndex(self.combo_first.currentIndex())
            self.combo_second.blockSignals(False)
        self.btn_place.setEnabled(bool(catalog.objects))
        self.btn_swap.setEnabled(bool(catalog.objects))
        self._update_preview()

    def update_pose(self, pose: Pose) -> None:
        """Запоминает текущую позу A для предпросмотра."""
        self._pose = pose
        self._update_preview()

    def preview_text(self) -> str:
        """Куда встанет B — для строки состояния."""
        first, second = self.selected_specs()
        if first is None or second is None:
            return EMPTY_TEXT
        try:
            target = join_pose(self._pose, first, second, self.request())
        except DomainError:
            return EMPTY_TEXT
        return f"X={format_length(target.x, 3)} Y={format_length(target.y, 3)} RZ={target.rz:.1f}°"

    def _update_preview(self) -> None:
        first, second = self.selected_specs()
        self._update_base_line()
        self._update_across_value(first, second)
        self._update_shift_line(first, second)
        texts = dict.fromkeys(self._value_labels, EMPTY_TEXT)
        if first is not None and second is not None:
            try:
                target = join_pose(self._pose, first, second, self.request())
            except DomainError:
                target = None
            if target is not None:
                texts = texts | {
                    "x": f"{format_length(target.x, 3)} м",
                    "y": f"{format_length(target.y, 3)} м",
                    "rz": f"{target.rz:.1f}°",
                }
        for key, label in self._value_labels.items():
            label.setText(texts[key])

    def swap_objects(self) -> None:
        """Меняет A и B местами для продолжения цепочки."""
        first = self.combo_first.currentIndex()
        second = self.combo_second.currentIndex()
        self.combo_first.blockSignals(True)
        self.combo_second.blockSignals(True)
        self.combo_first.setCurrentIndex(second)
        self.combo_second.setCurrentIndex(first)
        self.combo_first.blockSignals(False)
        self.combo_second.blockSignals(False)
        self._update_preview()

    def _update_shift_line(self, first: ObjectSpec | None, second: ObjectSpec | None) -> None:
        """Сдвиг от A в его собственных осях: поперёк и вдоль длины."""
        if first is None or second is None:
            self.lbl_shift.setText(EMPTY_TEXT)
            return
        try:
            across, along = local_offset(first, second, self.request())
        except DomainError:
            self.lbl_shift.setText(EMPTY_TEXT)
            return
        self.lbl_shift.setText(
            f"Сдвиг от A: {abs(across):.3f} м поперёк · {along:.3f} м вдоль длины"
        )

    def shift_text(self) -> str:
        """Строка сдвига в осях A (для тестов)."""
        return self.lbl_shift.text()

    def _update_base_line(self) -> None:
        pose = self._pose
        self.lbl_base.setText(
            f"A сейчас: X {format_length(pose.x, 2)} · Y {format_length(pose.y, 2)} · "
            f"угол {pose.rz:.1f}° — при установке угол перечитывается из панели"
        )

    def _update_across_value(self, first: ObjectSpec | None, second: ObjectSpec | None) -> None:
        field = AcrossField(self.combo_across.currentData())
        spec = first or second
        if spec is None:
            self.lbl_across.setText(EMPTY_TEXT)
            return
        value = spec.dimension(field.dimension)
        if value <= 0.0:
            self.lbl_across.setText(f"не измерено ({field.label.lower()})")
            return
        self.lbl_across.setText(f"{format_length(value, 3)} м")

    def base_line(self) -> str:
        """Строка про текущий угол A (для подсказок и тестов)."""
        return self.lbl_base.text()

    def across_text(self) -> str:
        """Поперечный размер, которым считается стык (для тестов)."""
        return self.lbl_across.text()

    def _select_name(self, combo: QComboBox, name: str) -> None:
        if not name:
            return
        for index in range(combo.count()):
            spec = combo.itemData(index)
            if isinstance(spec, ObjectSpec) and spec.key == name.strip().casefold():
                combo.setCurrentIndex(index)
                return
