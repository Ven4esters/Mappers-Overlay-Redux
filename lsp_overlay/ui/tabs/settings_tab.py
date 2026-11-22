"""Вкладка «Настройки»: шаг по умолчанию, защита, оформление."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.config import (
    CONFIRM_KEYS,
    DEFAULT_CLONE_DELETE_KEY,
    DEFAULT_CLONE_KEY,
    Settings,
    replace_settings,
)
from lsp_overlay.domain.directions import DiagonalMode
from lsp_overlay.domain.movement import MAX_MOVE_ROTATION, MIN_MOVE_ROTATION, MoveFrame
from lsp_overlay.ui.widgets import make_button, make_label, make_number_editor

OPACITY_SCALE = 100
DECIMALS_MAX = 6
PRESETS_SEPARATOR = ","


class SettingsTab(QWidget):
    """Правка настроек с явным сохранением."""

    settings_saved = Signal(object)
    status_message = Signal(str, str)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self._build_movement_group())
        layout.addWidget(self._build_protection_group())
        layout.addWidget(self._build_appearance_group())
        row = QHBoxLayout()
        row.addWidget(make_label("Изменения применяются после сохранения", muted=True), 1)
        self.btn_save = make_button("Сохранить настройки", object_name="primaryButton")
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_save)
        layout.addLayout(row)
        layout.addStretch(1)
        self.load(settings)

    # ------------------------------------------------------------------ группы
    def _build_movement_group(self) -> QGroupBox:
        group = QGroupBox("Движение")
        form = QFormLayout(group)
        self.spin_default_step = make_number_editor(3, minimum=0.001, maximum=500.0)
        form.addRow("Шаг по умолчанию, м", self.spin_default_step)
        self.edit_presets = QLineEdit()
        form.addRow("Пресеты шагов (через запятую)", self.edit_presets)
        self.combo_diagonal = QComboBox()
        self.combo_diagonal.addItem("Диагональ = шагу (÷√2)", DiagonalMode.SAME_DISTANCE.value)
        self.combo_diagonal.addItem("По шагу на каждую ось", DiagonalMode.SAME_STEP.value)
        form.addRow("Диагонали", self.combo_diagonal)
        self.combo_frame = QComboBox()
        for frame in MoveFrame:
            self.combo_frame.addItem(frame.label, frame.value)
        self.combo_frame.setToolTip(
            "Предмет (по умолчанию): стрелки идут по осям детали — при её углу боковой шаг "
            "меняет X и Y одновременно, и предмет едет ровно поперёк своей стороны. "
            "Мир: ↑ двигает на север (+Y), → на восток (+X), угол предмета не важен."
        )
        form.addRow("Оси движения", self.combo_frame)
        self.spin_rotation = make_number_editor(
            0, minimum=MIN_MOVE_ROTATION, maximum=MAX_MOVE_ROTATION
        )
        self.spin_rotation.setSuffix(" °")
        self.spin_rotation.setToolTip(
            "Поправка на поворот камеры, действует в осях мира: если камера смотрит не на "
            "север, поставьте здесь угол, под которым «вверх» на экране, — и стрелки "
            "совпадут с картинкой. 45° — камера развёрнута на северо-восток, 90° — на восток."
        )
        form.addRow("Поворот осей, °", self.spin_rotation)
        self.chk_tilt = QCheckBox("Учитывать наклоны RX/RY при движении")
        self.chk_tilt.setToolTip(
            "Выключите, если нужно двигать проп строго по полу, невзирая на его наклон."
        )
        form.addRow(self.chk_tilt)
        return group

    def _build_protection_group(self) -> QGroupBox:
        group = QGroupBox("Защита от «улёта»")
        form = QFormLayout(group)
        self.chk_verify = QCheckBox("Проверять поля после вставки")
        self.chk_verify.setToolTip(
            "После Ctrl+V значения перечитываются. Если панель их не приняла, "
            "прежние координаты возвращаются."
        )
        form.addRow(self.chk_verify)
        self.spin_max_jump = make_number_editor(1, minimum=0.0, maximum=1000.0)
        self.spin_max_jump.setToolTip("0 — отключить проверку (режим эксперта)")
        form.addRow("Максимальный шаг, м", self.spin_max_jump)
        self.combo_confirm = QComboBox()
        for key in CONFIRM_KEYS:
            self.combo_confirm.addItem(key.upper(), key)
        form.addRow("Клавиша подтверждения", self.combo_confirm)
        self.edit_clone_key = QLineEdit()
        self.edit_clone_key.setMaxLength(20)
        self.edit_clone_key.setToolTip("Клавиша, которая создаёт копию объекта (обычно C)")
        form.addRow("Клавиша копии", self.edit_clone_key)
        self.edit_clone_delete_key = QLineEdit()
        self.edit_clone_delete_key.setMaxLength(20)
        self.edit_clone_delete_key.setToolTip(
            "Клавиша удаления копии — нажимается только по кнопке «Убрать копию»"
        )
        form.addRow("Клавиша удаления копии", self.edit_clone_delete_key)
        self.chk_live_commit = QCheckBox("Подтверждать F в живом режиме (ставить предмет)")
        self.chk_live_commit.setToolTip(
            "Выключено: живой режим только показывает, где окажется предмет, и не нажимает F."
        )
        form.addRow(self.chk_live_commit)
        return group

    def _build_appearance_group(self) -> QGroupBox:
        group = QGroupBox("Окно")
        form = QFormLayout(group)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(20, 100)
        self.lbl_opacity = QLabel("94%")
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.slider_opacity, 1)
        row.addWidget(self.lbl_opacity)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        form.addRow("Прозрачность", holder)
        self.chk_on_top = QCheckBox("Поверх игры")
        form.addRow(self.chk_on_top)
        return group

    # ------------------------------------------------------------------ события
    def _on_opacity_changed(self, value: int) -> None:
        self.lbl_opacity.setText(f"{value}%")

    def load(self, settings: Settings) -> None:
        """Переносит значения из настроек в поля."""
        self._settings = settings
        self.spin_default_step.setValue(settings.step)
        self.edit_presets.setText(
            PRESETS_SEPARATOR.join(f"{value:g}" for value in settings.step_presets)
        )
        index = self.combo_diagonal.findData(settings.diagonal_mode.value)
        self.combo_diagonal.setCurrentIndex(max(index, 0))
        self.chk_tilt.setChecked(settings.use_tilt)
        self.spin_rotation.setValue(settings.move_rotation)
        self.combo_frame.setCurrentIndex(
            max(self.combo_frame.findData(settings.move_frame.value), 0)
        )
        self.chk_verify.setChecked(settings.verify_after_paste)
        self.spin_max_jump.setValue(settings.max_jump)
        self.combo_confirm.setCurrentIndex(
            max(self.combo_confirm.findData(settings.confirm_key), 0)
        )
        self.edit_clone_key.setText(settings.clone_key)
        self.edit_clone_delete_key.setText(settings.clone_delete_key)
        self.chk_live_commit.setChecked(settings.live_commit)
        self.slider_opacity.setValue(int(round(settings.overlay_opacity * OPACITY_SCALE)))
        self.chk_on_top.setChecked(settings.always_on_top)

    def _collect(self) -> Settings:
        presets = tuple(
            float(part.replace(",", "."))
            for part in self.edit_presets.text()
            .replace(";", PRESETS_SEPARATOR)
            .split(PRESETS_SEPARATOR)
            if part.strip()
        )
        return replace_settings(
            self._settings,
            step=self.spin_default_step.value(),
            step_presets=presets or self._settings.step_presets,
            diagonal_mode=DiagonalMode(self.combo_diagonal.currentData()),
            use_tilt=self.chk_tilt.isChecked(),
            move_frame=MoveFrame(str(self.combo_frame.currentData())),
            move_rotation=self.spin_rotation.value(),
            verify_after_paste=self.chk_verify.isChecked(),
            max_jump=self.spin_max_jump.value(),
            confirm_key=self.combo_confirm.currentData(),
            clone_key=self.edit_clone_key.text().strip().lower() or DEFAULT_CLONE_KEY,
            clone_delete_key=(
                self.edit_clone_delete_key.text().strip().lower() or DEFAULT_CLONE_DELETE_KEY
            ),
            live_commit=self.chk_live_commit.isChecked(),
            overlay_opacity=self.slider_opacity.value() / OPACITY_SCALE,
            always_on_top=self.chk_on_top.isChecked(),
            timings=self._settings.timings,
        ).validated()

    def _save(self) -> None:
        try:
            settings = self._collect()
        except (ValueError, TypeError) as error:
            self.status_message.emit(f"Настройки не сохранены: {error}", "error")
            return
        self._settings = settings
        self.settings_saved.emit(settings)
