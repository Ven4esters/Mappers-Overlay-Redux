"""Разбор чисел, скопированных из полей панели LSP."""

from __future__ import annotations

import math
import re
from typing import Final

from map_overlay.errors import ParseError

_NUMBER_PATTERN: Final = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_SPACES: Final = ("\u00a0", "\u202f", " ")


def _normalise(text: str) -> str:
    cleaned = text
    for space in _SPACES:
        cleaned = cleaned.replace(space, "")
    return cleaned.replace("\u2212", "-").replace(",", ".")


def parse_number(text: str) -> float:
    """Вытащить число из текста поля.

    Панель может отдать ``-1848.763``, ``-1848,763`` или ``20.00°`` — берём первое число.

    Raises:
        ParseError: если числа в тексте нет или оно не конечное.
    """
    if not text or not text.strip():
        raise ParseError("поле пустое")
    normalised = _normalise(text)
    match = _NUMBER_PATTERN.search(normalised)
    if match is None:
        raise ParseError(f"в поле нет числа: {text.strip()!r}")
    value = float(match.group())
    if not math.isfinite(value):
        raise ParseError(f"недопустимое число: {text.strip()!r}")
    return value
