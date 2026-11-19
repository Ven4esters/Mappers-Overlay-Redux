from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..hotkeys import parse_hotkey_spec
from ..models import AppSettings, HotkeyConfig, MacroTimings


HOTKEY_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("capture", "Захват координат из панели"),
    ("save_commit", "Сохранить (Клик мимо + Enter)"),
    ("paste_all", "Вставить все 6 координат"),
    ("calibrate_point", "Фиксация точки при калибровке"),
    ("move_forward", "Сдвиг Вперёд"),
    ("move_back", "Сдвиг Назад"),
    ("move_left", "Сдвиг Влево"),
    ("move_right", "Сдвиг Вправо"),
    ("move_up", "Сдвиг Вверх (+Z)"),
    ("move_down", "Сдвиг Вниз (-Z)"),
    ("rot_left_90", "Поворот +90° (против часовой)"),
    ("rot_right_90", "Поворот -90° (по часовой)"),
    ("undo", "Отменить действие (Undo)"),
)


class SettingsDialog(QDialog):
    """Диалог тонкой настройки таймингов макроса, округления, прозрачности и горячих клавиш."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки LSP Mapper Assist")
        self.setMinimumWidth(440)
        self._settings = settings

        root = QVBoxLayout(self)
        root.setSpacing(8)

        # 1. Окно и точность чисел
        ui_box = QGroupBox("Оверлей и округление чисел")
        ui_form = QFormLayout(ui_box)

        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(45, 100)
        self.opacity_slider.setValue(int(round(settings.window_opacity * 100)))
        self.opacity_label = QLabel(f"{self.opacity_slider.value()}%")
        self.opacity_slider.valueChanged.connect(lambda v: self.opacity_label.setText(f"{v}%"))
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_label)
        ui_form.addRow("Прозрачность окна:", opacity_row)

        self.pos_dec_spin = QSpinBox()
        self.pos_dec_spin.setRange(1, 6)
        self.pos_dec_spin.setValue(settings.pos_decimals)
        ui_form.addRow("Знаков после точки (X, Y, Z):", self.pos_dec_spin)

        self.rot_dec_spin = QSpinBox()
        self.rot_dec_spin.setRange(1, 6)
        self.rot_dec_spin.setValue(settings.rot_decimals)
        ui_form.addRow("Знаков после точки (Углы):", self.rot_dec_spin)

        root.addWidget(ui_box)

        # 2. Тайминги макроса
        timing_box = QGroupBox("Тайминги кликов и буфера (мс)")
        timing_form = QFormLayout(timing_box)

        self.spin_click = QSpinBox()
        self.spin_click.setRange(5, 300)
        self.spin_click.setSuffix(" мс")
        self.spin_click.setValue(settings.timings.click_delay_ms)
        timing_form.addRow("Пауза после клика в поле:", self.spin_click)

        self.spin_key = QSpinBox()
        self.spin_key.setRange(5, 300)
        self.spin_key.setSuffix(" мс")
        self.spin_key.setValue(settings.timings.key_delay_ms)
        timing_form.addRow("Пауза Ctrl+A / Ctrl+V:", self.spin_key)

        self.spin_handoff = QSpinBox()
        self.spin_handoff.setRange(15, 500)
        self.spin_handoff.setSuffix(" мс")
        self.spin_handoff.setValue(settings.timings.focus_handoff_ms)
        timing_form.addRow("Передача фокуса окну FiveM:", self.spin_handoff)

        self.spin_save_enter = QSpinBox()
        self.spin_save_enter.setRange(10, 400)
        self.spin_save_enter.setSuffix(" мс")
        self.spin_save_enter.setValue(settings.timings.save_enter_delay_ms)
        timing_form.addRow("Пауза «Клик мимо» -> Enter:", self.spin_save_enter)

        self.spin_clip_timeout = QSpinBox()
        self.spin_clip_timeout.setRange(50, 1000)
        self.spin_clip_timeout.setSuffix(" мс")
        self.spin_clip_timeout.setValue(settings.timings.clipboard_timeout_ms)
        timing_form.addRow("Таймаут чтения Ctrl+C:", self.spin_clip_timeout)

        root.addWidget(timing_box)

        # 3. Горячие клавиши
        hk_box = QGroupBox("Глобальные горячие клавиши (пример: F5, Alt+Right, Ctrl+Q)")
        hk_form = QFormLayout(hk_box)
        self.hk_inputs: dict[str, QLineEdit] = {}
        hk_dict = settings.hotkeys.to_dict()
        for key, label in HOTKEY_FIELD_LABELS:
            inp = QLineEdit(hk_dict.get(key, ""))
            inp.setPlaceholderText("Пусто — отключено")
            inp.textChanged.connect(lambda txt, widget=inp: self._validate_hk_input(widget, txt))
            self._validate_hk_input(inp, inp.text())
            self.hk_inputs[key] = inp
            hk_form.addRow(f"{label}:", inp)

        root.addWidget(hk_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _validate_hk_input(widget: QLineEdit, text: str) -> None:
        stripped = text.strip()
        if not stripped or parse_hotkey_spec(stripped) is not None:
            widget.setStyleSheet("")
        else:
            widget.setStyleSheet("border: 1px solid #ef4444;")

    def apply_to_settings(self) -> None:
        self._settings.window_opacity = self.opacity_slider.value() / 100.0
        self._settings.pos_decimals = self.pos_dec_spin.value()
        self._settings.rot_decimals = self.rot_dec_spin.value()

        self._settings.timings = MacroTimings(
            click_delay_ms=self.spin_click.value(),
            key_delay_ms=self.spin_key.value(),
            focus_handoff_ms=self.spin_handoff.value(),
            clipboard_timeout_ms=self.spin_clip_timeout.value(),
            save_enter_delay_ms=self.spin_save_enter.value(),
        )

        new_hk: dict[str, str] = {}
        old_hk = self._settings.hotkeys.to_dict()
        for key, inp in self.hk_inputs.items():
            txt = inp.text().strip()
            if not txt or parse_hotkey_spec(txt) is not None:
                new_hk[key] = txt
            else:
                new_hk[key] = old_hk.get(key, "")
        self._settings.hotkeys = HotkeyConfig.from_dict(new_hk)
