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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from map_overlay.config import MAX_DELAY_S, MIN_DELAY_S, Delays, Settings
from map_overlay.domain.actions import ACTION_ORDER, Action, hotkey_name
from map_overlay.domain.formatting import MAX_DECIMALS, MIN_DECIMALS
from map_overlay.domain.movement import MAX_STEP, MIN_STEP
from map_overlay.errors import AppError
from map_overlay.ui.widgets import (
    GRID_SPACING,
    ROW_SPACING,
    SECTION_GAP,
    Card,
    DecimalSpinBox,
    button,
    label,
)

DELAY_STEP_S = 0.01
STEP_SPIN_DECIMALS = 3
SPIN_WIDTH = 110
KEY_COLUMN_WIDTH = 62
NAME_COLUMN_WIDTH = 116
DELAY_LABEL_WIDTH = 116
# Колонка подписей задержек: поля в левой и правой половине начинаются с одного места.
VALUE_LABEL_WIDTH = 150

DELAY_HINT = (
    "Каждое поле — пауза после своего действия: клика, выделения, копирования, вставки.\n"
    "Если панель не успевает принять значения, увеличьте задержки на 20–40 мс."
)
VALUE_HINT = (
    "Знаков после запятой — сколько цифр оверлей вставляет в панель.\n"
    "Шаг по умолчанию подставляется в поле «Шаг» при запуске и после «Считать»."
)
HOTKEY_HINT = (
    "Клавиши забираются у игры; цифровому блоку нужен включённый NumLock.\n"
    "Игра не получает клавиатуру? Снимите галочку — перехват выключится сразу.\n"
    "«Изменить» назначает новую клавишу, «✕» снимает привязку."
)


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
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(SECTION_GAP)
        layout.addWidget(self._build_delays(settings))
        layout.addWidget(self._build_values(settings))
        layout.addWidget(self._build_hotkeys(settings))

        row = QHBoxLayout()
        save = button("Сохранить", widget_role="primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        path_label = label(f"Файл настроек: {self._describe_path()}", widget_role="hint")
        path_label.setWordWrap(False)
        row.addSpacing(12)
        row.addWidget(path_label, 1)
        layout.addLayout(row)
        layout.addStretch(1)

    def _build_delays(self, settings: Settings) -> QWidget:
        card = Card("Задержки обмена с панелью", hint=DELAY_HINT)
        self._delay_card = card
        self._click = _delay_spin(settings.delays.click)
        self._select = _delay_spin(settings.delays.select)
        self._copy = _delay_spin(settings.delays.copy)
        self._paste = _delay_spin(settings.delays.paste)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(GRID_SPACING)
        pairs = [
            ("После клика", self._click),
            ("После Ctrl+A", self._select),
            ("После Ctrl+C", self._copy),
            ("После Ctrl+V", self._paste),
        ]
        for index, (title, widget) in enumerate(pairs):
            column, row = divmod(index, 2)
            caption = label(title, widget_role="muted")
            caption.setWordWrap(False)
            caption.setMinimumWidth(DELAY_LABEL_WIDTH)
            grid.addWidget(caption, row, column * 2)
            grid.addWidget(widget, row, column * 2 + 1)
        grid.setColumnStretch(3, 1)
        card.add_layout(grid)
        return card

    def _build_values(self, settings: Settings) -> QWidget:
        card = Card("Значения", hint=VALUE_HINT)
        self._value_card = card
        self._decimals = QSpinBox(self)
        self._decimals.setRange(MIN_DECIMALS, MAX_DECIMALS)
        self._decimals.setValue(settings.decimals)
        _compact(self._decimals)
        self._default_step = DecimalSpinBox(self)
        self._default_step.setRange(MIN_STEP, MAX_STEP)
        self._default_step.setDecimals(STEP_SPIN_DECIMALS)
        self._default_step.setSingleStep(0.1)
        self._default_step.setValue(settings.default_step)
        self._default_step.setSuffix(" м")
        _compact(self._default_step)
        self._verify = QCheckBox("Проверять значение после вставки")
        self._verify.setChecked(settings.verify_writes)
        grid = QGridLayout()
        grid.setHorizontalSpacing(ROW_SPACING)
        grid.setVerticalSpacing(GRID_SPACING)
        for row, (title, widget) in enumerate(
            (("Знаков после запятой", self._decimals), ("Шаг по умолчанию", self._default_step))
        ):
            caption = label(title, widget_role="muted")
            caption.setWordWrap(False)
            caption.setMinimumWidth(VALUE_LABEL_WIDTH)
            grid.addWidget(caption, row, 0)
            grid.addWidget(widget, row, 1)
        grid.addWidget(self._verify, 2, 0, 1, 2)
        grid.setColumnStretch(2, 1)
        card.add_layout(grid)
        return card

    def _build_hotkeys(self, settings: Settings) -> QWidget:
        card = Card("Горячие клавиши", hint=HOTKEY_HINT)
        self._hotkey_card = card
        self._hotkeys_enabled = QCheckBox("Перехватывать клавиши у игры")
        self._hotkeys_enabled.setChecked(True)
        self._hotkeys_enabled.setToolTip(
            "Снимите галочку, если игра перестала получать клавиатуру: "
            "перехват выключится сразу, без перезапуска."
        )
        self._hotkeys_enabled.toggled.connect(self.hotkeys_enabled_changed)
        card.add(self._hotkeys_enabled)
        self._num_lock_warning = label("", widget_role="warn")
        self._num_lock_warning.hide()
        card.add(self._num_lock_warning)
        card.add_layout(self._build_hotkey_grid(settings))
        return card

    def _build_hotkey_grid(self, settings: Settings) -> QGridLayout:
        """Сетка «действие — клавиша — Изменить — Снять» в один столбец.

        В два столбца строки не помещались в окно шириной 640: правый столбец с кнопками
        уходил за границу прокручиваемой области.
        """
        grid = QGridLayout()
        grid.setHorizontalSpacing(ROW_SPACING)
        grid.setVerticalSpacing(4)
        for row, action in enumerate(ACTION_ORDER):
            self._add_hotkey_row(grid, settings, action, row)
        # Пустая растяжка справа: кнопки стоят сразу за клавишей, а не у правого края.
        grid.setColumnStretch(4, 1)
        return grid

    def _add_hotkey_row(
        self, grid: QGridLayout, settings: Settings, action: Action, row: int
    ) -> None:
        name = label(action.label, widget_role="muted")
        name.setMinimumWidth(NAME_COLUMN_WIDTH)
        key = label(hotkey_name(action, settings.hotkeys.get(action)), widget_role="poseValue")
        key.setMinimumWidth(KEY_COLUMN_WIDTH)
        change = button("Изменить", widget_role="small")
        change.clicked.connect(
            lambda _checked=False, selected=action: self.hotkey_change_requested.emit(selected)
        )
        clear = button("✕", widget_role="small", tooltip="Снять привязку", danger=True)
        clear.clicked.connect(
            lambda _checked=False, selected=action: self.hotkey_clear_requested.emit(selected)
        )
        grid.addWidget(name, row, 0)
        grid.addWidget(key, row, 1)
        grid.addWidget(change, row, 2)
        grid.addWidget(clear, row, 3)
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
            widget.setText(hotkey_name(action, hotkeys.get(action)))

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
    widget = DecimalSpinBox()
    widget.setRange(MIN_DELAY_S, MAX_DELAY_S)
    widget.setDecimals(2)
    widget.setSingleStep(DELAY_STEP_S)
    widget.setValue(value)
    widget.setSuffix(" с")
    _compact(widget)
    return widget
