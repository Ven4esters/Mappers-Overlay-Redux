"""Форматирование чисел для вставки в панель."""

from __future__ import annotations

from typing import Final

from map_overlay.errors import ValidationError

MIN_DECIMALS: Final = 0
MAX_DECIMALS: Final = 6


def check_decimals(decimals: int) -> int:
    """Проверить допустимое количество знаков после запятой."""
    if not MIN_DECIMALS <= decimals <= MAX_DECIMALS:
        raise ValidationError(
            f"Знаков после запятой должно быть от {MIN_DECIMALS} до {MAX_DECIMALS}, "
            f"получено {decimals}"
        )
    return decimals


def rounded(value: float, decimals: int) -> float:
    """Округлить значение и убрать «минус ноль»."""
    check_decimals(decimals)
    quantised = round(value, decimals)
    if quantised == 0:
        return 0.0
    return quantised


def format_value(value: float, decimals: int) -> str:
    """Число для вставки в поле панели: точка, фиксированное число знаков."""
    return f"{rounded(value, decimals):.{decimals}f}"


def format_delta(value: float, decimals: int = 3) -> str:
    """Приращение со знаком: ``+0.500``, ``-0.500``, ``0.000``."""
    quantised = rounded(value, decimals)
    if quantised == 0:
        return f"{0.0:.{decimals}f}"
    return f"{quantised:+.{decimals}f}"
