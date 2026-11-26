"""Разбор чисел из полей панели."""

from __future__ import annotations

import pytest
from map_overlay.domain.parsing import parse_number
from map_overlay.errors import ParseError


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1845.5", 1845.5),
        ("-1848.763", -1848.763),
        ("-1848,763", -1848.763),
        ("20.00°", 20.0),
        ("  -12.5  ", -12.5),
        ("\u221212.5", -12.5),
        ("\u00a01 234.5", 1234.5),
        ("0", 0.0),
    ],
)
def test_parse_number(text: str, expected: float) -> None:
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "не число", "—"])
def test_parse_number_rejects_garbage(text: str) -> None:
    with pytest.raises(ParseError):
        parse_number(text)
