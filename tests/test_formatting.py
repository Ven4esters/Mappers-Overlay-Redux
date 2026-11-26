"""Форматирование чисел для панели."""

from __future__ import annotations

import pytest
from map_overlay.domain.formatting import format_delta, format_value, rounded
from map_overlay.errors import ValidationError


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (1845.0, 3, "1845.000"),
        (-1848.7634, 3, "-1848.763"),
        (0.1 + 0.2, 3, "0.300"),
        (20.0, 2, "20.00"),
        (1.5, 0, "2"),
    ],
)
def test_format_value(value: float, decimals: int, expected: str) -> None:
    assert format_value(value, decimals) == expected


def test_negative_zero_becomes_zero() -> None:
    assert format_value(-0.0001, 3) == "0.000"
    assert rounded(-0.0, 3) == 0.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.5, "+0.500"), (-0.5, "-0.500"), (0.0, "0.000"), (-0.0001, "0.000")],
)
def test_delta_has_sign(value: float, expected: str) -> None:
    assert format_delta(value) == expected


@pytest.mark.parametrize("decimals", [-1, 7])
def test_decimals_out_of_range(decimals: int) -> None:
    with pytest.raises(ValidationError):
        format_value(1.0, decimals)
