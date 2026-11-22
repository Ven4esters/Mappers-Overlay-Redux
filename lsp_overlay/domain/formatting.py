"""Форматирование и разбор чисел так, как их понимает панель LSP."""

from __future__ import annotations

import math
import re

from lsp_overlay.domain.errors import ValidationError

LENGTH_DECIMALS = 4
ANGLE_DECIMALS = 2
DEGREE_SIGN = "°"
NUMBER_PATTERN = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def format_length(value: float, decimals: int = LENGTH_DECIMALS) -> str:
    """Число координаты без экспоненты и без «-0.0000».

    >>> format_length(250.5)
    '250.5000'
    >>> format_length(-0.00001)
    '0.0000'
    """
    if not math.isfinite(value):
        raise ValidationError("координата должна быть конечным числом")
    rounded = round(value, decimals)
    if rounded == 0.0:
        rounded = 0.0
    return f"{rounded:.{decimals}f}"


def format_angle(value: float, decimals: int = ANGLE_DECIMALS, *, with_sign: bool = True) -> str:
    """Угол строкой: ``'127.42°'`` (знак градуса опционален)."""
    if not math.isfinite(value):
        raise ValidationError("угол должен быть конечным числом")
    rounded = round(value, decimals)
    if rounded == 0.0:
        rounded = 0.0
    text = f"{rounded:.{decimals}f}"
    return f"{text}{DEGREE_SIGN}" if with_sign else text


def parse_number(text: str) -> float:
    """Разбирает число из поля ввода: пробелы, запятая и знак градуса допускаются."""
    cleaned = text.strip().replace(" ", "").replace(DEGREE_SIGN, "")
    if not cleaned:
        raise ValidationError("пустое значение")
    cleaned = cleaned.replace(",", ".")
    if not NUMBER_PATTERN.match(cleaned):
        raise ValidationError(f"«{text.strip()}» — не число")
    value = float(cleaned)
    if not math.isfinite(value):
        raise ValidationError("значение должно быть конечным числом")
    return value
