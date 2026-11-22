"""Мелкие фабрики виджетов, чтобы вкладки оставались читаемыми."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from lsp_overlay.ui.styles import MUTED


def make_button(
    text: str,
    tooltip: str = "",
    *,
    object_name: str = "",
    checkable: bool = False,
) -> QPushButton:
    """Кнопка с подсказкой и (опционально) собственным стилем."""
    button = QPushButton(text)
    if tooltip:
        button.setToolTip(tooltip)
    if object_name:
        button.setObjectName(object_name)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def make_label(text: str, *, muted: bool = False, wrap: bool = False) -> QLabel:
    """Подпись, при необходимости приглушённая и с переносом строк."""
    label = QLabel(text)
    if muted:
        label.setObjectName("hintLabel")
        label.setStyleSheet(f"color: {MUTED};")
    label.setWordWrap(wrap)
    return label


def make_number_editor(
    decimals: int = 4, *, minimum: float = -1e6, maximum: float = 1e6
) -> QDoubleSpinBox:
    """Поле ввода числа без стрелок (иначе при кастомном стиле теряется текст)."""
    editor = QDoubleSpinBox()
    editor.setDecimals(decimals)
    editor.setRange(minimum, maximum)
    editor.setSingleStep(0.05)
    editor.setKeyboardTracking(False)
    editor.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
    editor.setAlignment(Qt.AlignmentFlag.AlignRight)
    editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return editor


def hline_spacer() -> QWidget:
    """Растягивающаяся пустышка для выравнивания по краям."""
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return spacer
