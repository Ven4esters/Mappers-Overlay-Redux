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


class _HookHarness:
    """Хук с поддельным событием клавиатуры: проверяем решение без Windows."""

    def __init__(self, bound: tuple[int, ...] = (0x68,), learning: bool = False) -> None:
        import ctypes

        from map_overlay.infrastructure.hotkeys import WindowsHotkeySource, _KeyboardHookData

        self.ctypes = ctypes
        self.source = WindowsHotkeySource()
        self.source._bound = frozenset(bound)
        self.source._learning = learning
        self.source._enabled = True
        self.source._call_next = lambda *args: 0
        self.events: list[tuple[int, bool, bool]] = []
        self.source.key_event.connect(lambda vk, down, fresh: self.events.append((vk, down, fresh)))
        self._data = _KeyboardHookData(vk=0, scan=0, flags=0, time=0, extra=None)

    def send(self, vk: int, is_down: bool, *, injected: bool = False) -> int:
        """Отправить нажатие или отпускание и вернуть решение хука."""
        from map_overlay.infrastructure.hotkeys import LLKHF_INJECTED, WM_KEYDOWN, WM_KEYUP

        self._data.vk = vk
        self._data.flags = LLKHF_INJECTED if injected else 0
        message = WM_KEYDOWN if is_down else WM_KEYUP
        return int(self.source._decide(0, message, self.ctypes.addressof(self._data)))


def test_single_alt_tap_is_reported_as_toggle() -> None:
    hook = _HookHarness()
    # Alt не забирается у игры: отпускание и нажатие проходят как есть.
    assert hook.send(0x12, True) == 0
    assert hook.send(0x12, False) == 0
    assert hook.events == [(0x12, True, True)]


def test_alt_with_another_key_is_a_combination() -> None:
    hook = _HookHarness()
    hook.send(0x12, True)
    hook.send(0x68, True)
    hook.send(0x68, False)
    hook.send(0x12, False)
    assert (0x12, True, True) not in hook.events


def test_alt_tap_is_ignored_while_learning() -> None:
    hook = _HookHarness(learning=True)
    hook.send(0x12, True)
    hook.send(0x12, False)
    assert hook.events == []


def test_alt_tap_is_ignored_when_interception_is_off() -> None:
    hook = _HookHarness()
    hook.source._enabled = False
    hook.send(0x12, True)
    hook.send(0x12, False)
    assert hook.events == []


def test_single_alt_tap_arrives_with_a_side_code() -> None:
    """Настоящий хук присылает 0xA4 (левый Alt) — переключатель должен сработать."""
    hook = _HookHarness()
    hook.send(0xA4, True)
    hook.send(0xA4, False)
    assert hook.events == [(0x12, True, True)]


def test_injected_keys_do_not_break_the_alt_tap() -> None:
    """Ctrl+A/Ctrl+V оверлея не превращают нажатие Alt в комбинацию."""
    hook = _HookHarness()
    hook.send(0xA4, True)
    hook.send(0x11, True, injected=True)
    hook.send(0x41, True, injected=True)
    hook.send(0x41, False, injected=True)
    hook.send(0x11, False, injected=True)
    hook.send(0xA4, False)
    assert hook.events == [(0x12, True, True)]


def test_side_codes_are_swallowed_for_bound_keys() -> None:
    """Горячая клавиша на Ctrl сработает, хотя хук присылает 0xA2."""
    hook = _HookHarness(bound=(0x11,))
    assert hook.send(0xA2, True) == 1
    assert hook.events == [(0x11, True, True)]


def test_frozen_hook_swallows_every_key() -> None:
    """Пока идёт обмен с панелью, клавиши не доходят ни до игры, ни до интерфейса."""
    hook = _HookHarness(bound=(0x68,))
    hook.source.freeze(True)
    assert hook.send(0x68, True) == 1
    assert hook.send(0x68, False) == 1
    assert hook.send(0x41, True) == 1
    assert hook.send(0x41, False) == 1
    assert hook.events == []


def test_frozen_hook_does_not_toggle_the_mode() -> None:
    """Alt во время обмена не переключает режим: клавиатура закрыта."""
    hook = _HookHarness()
    hook.source.freeze(True)
    hook.send(0xA4, True)
    hook.send(0xA4, False)
    assert hook.events == []


def test_unfrozen_hook_works_again() -> None:
    hook = _HookHarness(bound=(0x68,))
    hook.source.freeze(True)
    hook.send(0x68, True)
    hook.source.freeze(False)
    assert hook.send(0x68, True) == 1
    assert hook.events == [(0x68, True, True)]


def test_freeze_is_lifted_after_the_limit() -> None:
    """Забытая заморозка снимается сама: клавиатура не может остаться мертвой."""
    hook = _HookHarness()
    hook.source.freeze(True)
    hook.source._frozen_at -= 60.0
    assert hook.send(0x41, True) == 0
    assert hook.source._frozen is False


def test_frozen_hook_passes_its_own_keys_through() -> None:
    """Ctrl+A/Ctrl+V оверлея обязаны дойти до панели, даже когда клавиатура заморожена.

    Именно на этом сломался 1.4.1: заморозка съедала собственные клавиши, поле не
    менялось, а проверка читала буфер, который оверлей сам же и положил.
    """
    hook = _HookHarness()
    hook.source.freeze(True)
    assert hook.send(0x11, True, injected=True) == 0  # Ctrl
    assert hook.send(0x41, True, injected=True) == 0  # A
    assert hook.send(0x41, False, injected=True) == 0
    assert hook.send(0x56, True, injected=True) == 0  # V
    assert hook.send(0x11, False, injected=True) == 0
    assert hook.events == []


def test_frozen_hook_still_blocks_live_keys_next_to_its_own() -> None:
    hook = _HookHarness()
    hook.source.freeze(True)
    assert hook.send(0x11, True, injected=True) == 0
    assert hook.send(0x41, True) == 1
    assert hook.send(0x41, False) == 1
