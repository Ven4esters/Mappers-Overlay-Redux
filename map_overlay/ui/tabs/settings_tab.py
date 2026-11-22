"""Вкладка настроек: задержки обмена, точность, проверка записи."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from map_overlay.config import (
    MAX_DELAY_S,
    MIN_DELAY_S,
    Delays,
    Settings,
)
from map_overlay.domain.formatting import MAX_DECIMALS, MIN_DECIMALS
from map_overlay.domain.movement import MAX_STEP, MIN_STEP
from map_overlay.ui.widgets import Card, button, label

DELAY_STEP_S = 0.01
STEP_SPIN_DECIMALS = 3
SPIN_WIDTH = 110


class SettingsTab(QWidget):
    """Правка настроек с сохранением в файл."""

    settings_saved = Signal(object)
    status_message = Signal(str)

    def __init__(
        self,
        *,
        settings: Settings,
        config_path: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial = settings
        self._config_path = config_path
        self._build(settings)

    def _build(self, settings: Settings) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        delays_card = Card("Задержки обмена с панелью")
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self._click = _delay_spin(settings.delays.click)
        self._select = _delay_spin(settings.delays.select)
        self._copy = _delay_spin(settings.delays.copy)
        self._paste = _delay_spin(settings.delays.paste)
        form.addRow(label("После клика", widget_role="muted"), self._click)
        form.addRow(label("После Ctrl+A", widget_role="muted"), self._select)
        form.addRow(label("После Ctrl+C", widget_role="muted"), self._copy)
        form.addRow(label("После Ctrl+V", widget_role="muted"), self._paste)
        delays_card.add_layout(form)
        delays_card.add(
            label(
                "Если панель не успевает принять значения, увеличьте задержки на 20–40 мс.",
                widget_role="muted",
            )
        )
        layout.addWidget(delays_card)

        values_card = Card("Значения")
        values_form = QFormLayout()
        values_form.setHorizontalSpacing(14)
        values_form.setVerticalSpacing(8)
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
        values_form.addRow(label("Знаков после запятой", widget_role="muted"), self._decimals)
        values_form.addRow(label("Шаг по умолчанию", widget_role="muted"), self._default_step)
        values_form.addRow(self._verify)
        values_card.add_layout(values_form)
        layout.addWidget(values_card)

        row = QHBoxLayout()
        save = button("Сохранить", widget_role="primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(label(f"Файл настроек: {self._describe_path()}", widget_role="muted"))
        layout.addStretch(1)

    def _describe_path(self) -> str:
        return str(self._config_path) if self._config_path is not None else "ещё не сохранён"

    def _save(self) -> None:
        try:
            settings = self.collect()
        except Exception as exc:
            self.status_message.emit(str(exc))
            return
        self.settings_saved.emit(settings)

    def collect(self) -> Settings:
        """Собрать настройки из полей формы.

        Raises:
            ConfigError: если значения недопустимы.
        """
        return Settings(
            delays=Delays(
                click=self._click.value(),
                select=self._select.value(),
                copy=self._copy.value(),
                paste=self._paste.value(),
            ),
            decimals=self._decimals.value(),
            verify_writes=self._verify.isChecked(),
            default_step=self._default_step.value(),
            calibration=self._initial.calibration,
        )


def _compact(widget: QAbstractSpinBox) -> None:
    """Убрать крошечные кнопки «вверх/вниз»: значение вводится с клавиатуры."""
    widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
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
