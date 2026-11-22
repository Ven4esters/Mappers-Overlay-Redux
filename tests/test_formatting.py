from __future__ import annotations

import pytest
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.formatting import (
    format_angle,
    format_length,
    parse_number,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(250.5, "250.5000"), (-810.25, "-810.2500"), (0.0, "0.0000"), (31.00001, "31.0000")],
)
def test_format_length(value: float, expected: str) -> None:
    assert format_length(value) == expected


def test_format_length_never_outputs_negative_zero() -> None:
    assert format_length(-0.00001) == "0.0000"


def test_format_length_respects_decimals() -> None:
    assert format_length(1.234567, decimals=2) == "1.23"


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_format_length_rejects_nonfinite(value: float) -> None:
    with pytest.raises(ValidationError):
        format_length(value)


def test_format_angle_has_degree_sign() -> None:
    assert format_angle(127.42) == "127.42°"
    assert format_angle(-0.001) == "0.00°"
    assert format_angle(90.0, with_sign=False) == "90.00"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("250.5", 250.5), (" 250,5 ", 250.5), ("-0.25", -0.25), ("127.42°", 127.42), ("+5", 5.0)],
)
def test_parse_number_accepts_user_input(text: str, expected: float) -> None:
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", "12.34.56", "1e5", "--3", "250.5.1"])
def test_parse_number_rejects_garbage(text: str) -> None:
    with pytest.raises(ValidationError):
        parse_number(text)
