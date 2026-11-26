"""Тема и доступность: контраст текста, видимый фокус, имена для скрин-ридера.

Числа взяты из книги «Настольная книга UI/UX»: контраст основного текста — не ниже
4,5 : 1, зона клика на десктопе — не меньше 24 × 24 px, у каждой кнопки-значка есть
доступное имя. Проверки автоматические: иначе «читаемость» остаётся вкусом.
"""

from __future__ import annotations

from typing import Final

import pytest
from map_overlay.ui import theme
from map_overlay.ui.widgets import DirectionPad
from PySide6.QtWidgets import QApplication

MIN_TEXT_CONTRAST: Final = 4.5
# WCAG 2.2 AA для основного текста.

MIN_CLICK_PX: Final = 24
# Минимальная зона клика на десктопе — из главы 2 книги UI/UX.

TEXT_PAIRS: Final = (
    ("TEXT", "BACKGROUND"),
    ("TEXT", "SURFACE"),
    ("TEXT", "SURFACE_RAISED"),
    ("MUTED", "BACKGROUND"),
    ("MUTED", "SURFACE"),
    ("WARNING", "SURFACE"),
    ("DANGER_TEXT", "SURFACE"),
    ("SUCCESS", "SURFACE"),
)
# Пары «цвет текста — цвет поверхности», которые обязаны читаться.


def relative_luminance(color: str) -> float:
    """Относительная яркость цвета по WCAG."""
    value = color.lstrip("#")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """Контраст двух цветов: от 1 : 1 до 21 : 1."""
    brighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (brighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize(("text", "surface"), TEXT_PAIRS)
def test_text_contrast_meets_wcag_aa(text: str, surface: str) -> None:
    ratio = contrast_ratio(getattr(theme, text), getattr(theme, surface))
    assert ratio >= MIN_TEXT_CONTRAST, f"{text} на {surface}: {ratio:.2f} : 1"


def test_primary_button_text_is_readable() -> None:
    """Белый текст на акцентной заливке — тоже текст, порог тот же."""
    ratio = contrast_ratio("#ffffff", "#2563eb")
    assert ratio >= MIN_TEXT_CONTRAST


def test_focus_visible_in_stylesheet() -> None:
    """Фокус нарисован для кнопок, полей и списков: без него клавиатура «слепая»."""
    for selector in ("QPushButton:focus", "QComboBox:focus", "QLineEdit:focus"):
        assert selector in theme.APP_QSS


def test_arrow_buttons_have_accessible_names(qt_app: QApplication) -> None:
    """Стрелка — кнопка-значок: без имени скрин-ридер прочитает только символ."""
    pad = DirectionPad()
    try:
        for direction, item in pad._by_direction.items():
            assert item.accessibleName() == direction.label
            assert item.minimumWidth() >= MIN_CLICK_PX
            assert item.minimumHeight() >= MIN_CLICK_PX
    finally:
        pad.deleteLater()
