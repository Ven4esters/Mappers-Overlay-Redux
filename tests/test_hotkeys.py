"""Hotkey parsing / normalization tests (pure stdlib). / Тесты разбора хоткеев."""

from __future__ import annotations

from app.hotkey_parse import (
    DEFAULT_HOTKEY, is_reserved, normalize_hotkey, to_windows,
)


def test_normalize_basic_and_order() -> None:
    assert normalize_hotkey("ctrl+shift+q") == "Ctrl+Shift+Q"
    assert normalize_hotkey("shift+ctrl+q") == "Ctrl+Shift+Q"
    assert normalize_hotkey("ALT+F9") == "Alt+F9"
    assert normalize_hotkey(" meta + SPACE ") == "Meta+Space"


def test_normalize_aliases() -> None:
    assert normalize_hotkey("printscreen") == "Print"
    assert normalize_hotkey("PrtSc") == "Print"
    assert normalize_hotkey("esc") == "Escape"
    assert normalize_hotkey("PgUp") == "PageUp"
    assert normalize_hotkey("enter") == "Return"


def test_normalize_rejects_garbage() -> None:
    assert normalize_hotkey("") is None
    assert normalize_hotkey("Ctrl+") is None
    assert normalize_hotkey("Ctrl+Ctrl+Q") is None
    assert normalize_hotkey("Foo+Q") is None
    assert normalize_hotkey("Ctrl+Shift") is None
    assert normalize_hotkey("Ctrl+Shift+Key") is None
    assert normalize_hotkey("+") is None


def test_to_windows_values() -> None:
    assert to_windows("Ctrl+Shift+Q") == (0x0002 | 0x0004, 0x51)
    assert to_windows("Print") == (0x0000, 0x2C)
    assert to_windows("F9") == (0x0000, 0x78)
    assert to_windows("Alt+F4") == (0x0001, 0x73)
    assert to_windows("Shift+5") == (0x0004, 0x35)
    assert to_windows("Meta+Left") == (0x0008, 0x25)
    assert to_windows("bogus combo") is None


def test_roundtrip_default_is_print() -> None:
    assert DEFAULT_HOTKEY == "Print"
    assert to_windows(DEFAULT_HOTKEY) == (0x0000, 0x2C)


def test_reserved_combos() -> None:
    assert is_reserved("Ctrl+Shift+S")
    assert is_reserved("shift+ctrl+r")
    assert not is_reserved("Ctrl+Shift+Q")
    assert not is_reserved("Print")
