"""Подписи клавиш и проверка кодов."""

from __future__ import annotations

import pytest
from map_overlay.domain.keynames import (
    VK_DOWN,
    VK_ESCAPE,
    VK_F1,
    VK_NUMLOCK,
    VK_NUMPAD0,
    VK_NUMPAD9,
    is_numpad,
    is_valid_vk,
    key_name,
)


@pytest.mark.parametrize(
    ("vk", "expected"),
    [
        (None, "не назначена"),
        (VK_NUMPAD0, "Num 0"),
        (VK_NUMPAD9, "Num 9"),
        (VK_F1, "F1"),
        (VK_DOWN, "↓"),
        (VK_ESCAPE, "Esc"),
        (VK_NUMLOCK, "NumLock"),
        (0x41, "A"),
        (0xFE, "VK FE"),
    ],
)
def test_key_name(vk: int | None, expected: str) -> None:
    assert key_name(vk) == expected


@pytest.mark.parametrize(
    ("vk", "expected"),
    [(VK_NUMPAD0, True), (VK_NUMPAD9, True), (VK_F1, False), (None, False)],
)
def test_is_numpad(vk: int | None, expected: bool) -> None:
    assert is_numpad(vk) is expected


@pytest.mark.parametrize(
    ("vk", "expected"),
    [(0x01, True), (0x41, True), (0x00, False), (0xFF, False), (True, False), ("A", False)],
)
def test_is_valid_vk(vk: object, expected: bool) -> None:
    assert is_valid_vk(vk) is expected
