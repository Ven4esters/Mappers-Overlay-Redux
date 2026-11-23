"""Вкладка настроек: задержки, точность, горячие клавиши."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from map_overlay.config import MAX_DELAY_S, MIN_DELAY_S, Delays, Settings
from map_overlay.domain.actions import ACTION_ORDER, Action
from map_overlay.domain.formatting import MAX_DECIMALS, MIN_DECIMALS
from map_overlay.domain.keynames import key_name
from map_overlay.domain.movement import MAX_STEP, MIN_STEP
from map_overlay.errors import AppError
from map_overlay.ui.widgets import Card, button, label

DELAY_STEP_S = 0.01
STEP_SPIN_DECIMALS = 3
SPIN_WIDTH = 110
KEY_COLUMN_WIDTH = 62
NAME_COLUMN_WIDTH = 116
HOTKEY_COLUMN_GAP = 18
HOTKEY_ROWS = 5


class SettingsTab(QWidget):
    """Правка настроек и привязок клавиш."""

    settings_saved = Signal(object)
    status_message = Signal(str)
    hotkey_change_requested = Signal(object)
    hotkey_clear_requested = Signal(object)
    hotkeys_enabled_changed = Signal(bool)

    def __init__(
        self,
        *,
        settings: Settings,
        config_path: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._base = settings
        self._config_path = config_path
        self._key_labels: dict[Action, QLabel] = {}
        self._build(settings)

    def _build(self, settings: Settings) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(self._build_delays(settings))
        layout.addWidget(self._build_values(settings))
        layout.addWidget(self._build_hotkeys(settings))

        row = QHBoxLayout()
        save = button("Сохранить", widget_role="primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        path_label = label(f"Файл настроек: {self._describe_path()}", widget_role="muted")
        path_label.setWordWrap(False)
        row.addSpacing(12)
        row.addWidget(path_label, 1)
        layout.addLayout(row)
        layout.addStretch(1)

    def _build_delays(self, settings: Settings) -> QWidget:
        card = Card("Задержки обмена с панелью")
        self._click = _delay_spin(settings.delays.click)
        self._select = _delay_spin(settings.delays.select)
        self._copy = _delay_spin(settings.delays.copy)
        self._paste = _delay_spin(settings.delays.paste)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        pairs = [
            ("После клика", self._click),
            ("После Ctrl+A", self._select),
            ("После Ctrl+C", self._copy),
            ("После Ctrl+V", self._paste),
        ]
        for index, (title, widget) in enumerate(pairs):
            column, row = divmod(index, 2)
            grid.addWidget(label(title, widget_role="muted"), row, column * 2)
            grid.addWidget(widget, row, column * 2 + 1)
        card.add_layout(grid)
        card.add(
            label(
                "Если панель не успевает принять значения, увеличьте задержки на 20–40 мс.",
                widget_role="muted",
            )
        )
        return card

    def _build_values(self, settings: Settings) -> QWidget:
        card = Card("Значения")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self._decimals = QSpinBox(self)
        self._decimals.setRange(MIN_DECIMALS, MAX_DECIMALS)
        self._decimals.setValue(settings.decimals)
        _compact(self._decimals)
        self._default_step = QDoubleSpinBox(self)
        self._default_step.setRange(MIN_STEP, MAX_STEP)
        self._default_step.setDecimals(STEP_SPIN_DECIMALS)
        self._default_step.setSingleStep(0.1)
        self._default_step.setValue(settings.default_step)
        self._default_step.setSuffix(" м")
        _compact(self._default_step)
        self._verify = QCheckBox("Проверять значение после вставки")
        self._verify.setChecked(settings.verify_writes)
        inline = QHBoxLayout()
        inline.setSpacing(10)
        inline.addWidget(label("Знаков после запятой", widget_role="muted"))
        inline.addWidget(self._decimals)
        inline.addSpacing(12)
        inline.addWidget(label("Шаг по умолчанию", widget_role="muted"))
        inline.addWidget(self._default_step)
        inline.addStretch(1)
        card.add_layout(inline)
        form.addRow(self._verify)
        card.add_layout(form)
        return card

    def _build_hotkeys(self, settings: Settings) -> QWidget:
        card = Card("Горячие клавиши")
        self._hotkeys_enabled = QCheckBox("Перехватывать клавиши у игры")
        self._hotkeys_enabled.setChecked(True)
        self._hotkeys_enabled.setToolTip(
            "Снимите галочку, если игра перестала получать клавиатуру: "
            "перехват выключится сразу, без перезапуска."
        )
        self._hotkeys_enabled.toggled.connect(self.hotkeys_enabled_changed)
        card.add(self._hotkeys_enabled)
        card.add(
            label(
                "Игра не получает клавиатуру? Снимите галочку — перехват выключится сразу.",
                widget_role="muted",
            )
        )
        self._num_lock_warning = label("", widget_role="warn")
        self._num_lock_warning.hide()
        card.add(self._num_lock_warning)
        card.add_layout(self._build_hotkey_grid(settings))
        card.add(
            label(
                "Клавиши забираются у игры; цифровому блоку нужен включённый NumLock.",
                widget_role="muted",
            )
        )
        return card

    def _build_hotkey_grid(self, settings: Settings) -> QGridLayout:
        """Сетка «действие — клавиша — Изменить — Снять» в два столбца."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for index, action in enumerate(ACTION_ORDER):
            column, row = divmod(index, HOTKEY_ROWS)
            base = column * 5
            self._add_hotkey_row(grid, settings, action, row, base)
        grid.setColumnMinimumWidth(4, HOTKEY_COLUMN_GAP)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(6, 1)
        return grid

    def _add_hotkey_row(
        self, grid: QGridLayout, settings: Settings, action: Action, row: int, base: int
    ) -> None:
        name = label(action.label, widget_role="muted")
        name.setMinimumWidth(NAME_COLUMN_WIDTH)
        key = label(key_name(settings.hotkeys.get(action)), widget_role="poseValue")
        key.setMinimumWidth(KEY_COLUMN_WIDTH)
        change = button("Изменить", widget_role="small")
        change.clicked.connect(
            lambda _checked=False, selected=action: self.hotkey_change_requested.emit(selected)
        )
        clear = button("✕", widget_role="small", tooltip="Снять привязку")
        clear.clicked.connect(
            lambda _checked=False, selected=action: self.hotkey_clear_requested.emit(selected)
        )
        grid.addWidget(name, row, base)
        grid.addWidget(key, row, base + 1)
        grid.addWidget(change, row, base + 2)
        grid.addWidget(clear, row, base + 3)
        self._key_labels[action] = key

    def _describe_path(self) -> str:
        return str(self._config_path) if self._config_path is not None else "ещё не сохранён"

    def _save(self) -> None:
        try:
            settings = self.collect()
        except AppError as exc:  # текст для пользователя уже готов
            self.status_message.emit(str(exc))
            return
        self.settings_saved.emit(settings)

    def collect(self) -> Settings:
        """Собрать настройки из полей формы, сохранив калибровку и клавиши.

        Raises:
            ConfigError: если значения недопустимы.
        """
        return replace(
            self._base,
            delays=Delays(
                click=self._click.value(),
                select=self._select.value(),
                copy=self._copy.value(),
                paste=self._paste.value(),
            ),
            decimals=self._decimals.value(),
            verify_writes=self._verify.isChecked(),
            default_step=self._default_step.value(),
        )

    def set_base_settings(self, settings: Settings) -> None:
        """Обновить основу: калибровка и клавиши меняются на других вкладках."""
        self._base = settings
        self.set_hotkeys(settings.hotkeys)

    def set_hotkeys(self, hotkeys: Mapping[Action, int | None]) -> None:
        """Показать текущие привязки клавиш."""
        for action, widget in self._key_labels.items():
            widget.setText(key_name(hotkeys.get(action)))

    def set_num_lock_warning(self, text: str) -> None:
        """Предупредить о выключенном NumLock."""
        self._num_lock_warning.setText(text)
        self._num_lock_warning.setVisible(bool(text))

    def hotkeys_enabled(self) -> bool:
        """Включён ли перехват клавиш (для тестов)."""
        return self._hotkeys_enabled.isChecked()


def _compact(widget: QAbstractSpinBox) -> None:
    """Убрать крошечные кнопки «вверх/вниз»: значение вводится с клавиатуры."""
    widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    widget.setMinimumWidth(SPIN_WIDTH)
    widget.setMaximumWidth(SPIN_WIDTH)


def _delay_spin(value: float) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(MIN_DELAY_S, MAX_DELAY_S)
    widget.setDecimals(2)
    widget.setSingleStep(DELAY_STEP_S)
    widget.setValue(value)
    widget.setSuffix(" с")
    _compact(widget)
    return widget
