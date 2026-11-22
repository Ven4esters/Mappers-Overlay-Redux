"""Инфраструктура: буфер обмена, часы, Win32-заглушки и сообщения об ошибках."""

from __future__ import annotations

import sys

import pyperclip
import pytest
from map_overlay.errors import ClipboardError, UnsupportedPlatformError
from map_overlay.infrastructure.clipboard import SystemClipboard
from map_overlay.infrastructure.clock import SystemClock
from map_overlay.infrastructure.win32_input import WindowsInput, enable_dpi_awareness


def test_clipboard_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = {"text": ""}
    monkeypatch.setattr(pyperclip, "copy", lambda text: storage.update(text=text))
    monkeypatch.setattr(pyperclip, "paste", lambda: storage["text"])
    clipboard = SystemClipboard()
    clipboard.set("1845.000")
    assert clipboard.get() == "1845.000"


def test_clipboard_failure_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> str:
        raise pyperclip.PyperclipException("нет доступа")

    monkeypatch.setattr(pyperclip, "paste", broken)
    with pytest.raises(ClipboardError, match="Буфер обмена недоступен"):
        SystemClipboard().get()


def test_clipboard_write_failure_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_text: str) -> None:
        raise pyperclip.PyperclipException("нет доступа")

    monkeypatch.setattr(pyperclip, "copy", broken)
    with pytest.raises(ClipboardError, match="Не удалось записать"):
        SystemClipboard().set("1")


def test_clock_ignores_zero_pause() -> None:
    SystemClock().sleep(0)
    SystemClock().sleep(0.001)


@pytest.mark.skipif(sys.platform == "win32", reason="проверяем поведение вне Windows")
def test_windows_input_refuses_other_platforms() -> None:
    with pytest.raises(UnsupportedPlatformError):
        WindowsInput()


@pytest.mark.skipif(sys.platform == "win32", reason="DPI включается только в Windows")
def test_dpi_awareness_is_false_off_windows() -> None:
    assert enable_dpi_awareness() is False
