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


@pytest.mark.skipif(sys.platform == "win32", reason="проверяем поведение вне Windows")
def test_windows_hotkey_source_refuses_other_platforms() -> None:
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    events: list[tuple[int, bool]] = []
    source = WindowsHotkeySource()
    source.start_listening(lambda vk, is_down, fresh: events.append((vk, is_down)))
    assert source.failed is True
    assert source.is_available() is False
    assert source.num_lock_enabled() is None
    source.stop_listening()
    assert events == []


@pytest.mark.skipif(sys.platform == "win32", reason="проверяем поведение вне Windows")
def test_modifier_state_off_windows_is_off() -> None:
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    source = WindowsHotkeySource()
    assert source.alt_down() is False
    assert source.key_down(0x68) is False


def test_hook_decides_fresh_press_and_autorepeat(
    qt_app: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Решение хука: первое нажатие свежее, автоповтор — нет, отпускание — нет."""
    import ctypes

    from map_overlay.infrastructure.hotkeys import (
        WM_KEYDOWN,
        WM_KEYUP,
        WindowsHotkeySource,
        _KeyboardHookData,
    )

    source = WindowsHotkeySource()
    source._bound = frozenset({0x68})
    source._enabled = True
    source._call_next = lambda *args: 0
    events: list[tuple[int, bool, bool]] = []
    source.key_event.connect(lambda vk, down, fresh: events.append((vk, down, fresh)))
    data = _KeyboardHookData(vk=0x68, scan=0, flags=0, time=0, extra=None)
    lparam = ctypes.addressof(data)

    with caplog.at_level("INFO"):
        assert source._decide(0, WM_KEYDOWN, lparam) == 1
        assert source._decide(0, WM_KEYDOWN, lparam) == 1
        assert source._decide(0, WM_KEYUP, lparam) == 1
    assert events == [(0x68, True, True), (0x68, True, False), (0x68, False, False)]
    # В журнал попадает только само нажатие: автоповтор и отпускание молчат.
    assert caplog.text.count("Хук забрал клавишу Num 8") == 1
