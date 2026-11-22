"""Глобальный хук Numpad: без него игра вертит камеру и двигает объект сама."""

from __future__ import annotations

from lsp_overlay.infrastructure.global_keys import (
    NUMPAD_FIRST_VK,
    NUMPAD_LAST_VK,
    NullKeyHook,
    Win32KeyHook,
)
from lsp_overlay.ui.keymap import NUMPAD_VK


def test_null_hook_never_captures() -> None:
    hook = NullKeyHook()
    assert not hook.is_available()
    assert not hook.start(lambda _vk, _pressed: None)
    hook.stop()


def test_win32_hook_is_unavailable_off_windows() -> None:
    hook = Win32KeyHook()
    if hook.is_available():  # pragma: no cover - на Windows проверяем установку
        assert hook.start(lambda _vk, _pressed: None)
        hook.stop()
    else:
        assert not hook.start(lambda _vk, _pressed: None)
        hook.stop()


def test_numpad_range_covers_every_direction_key() -> None:
    assert NUMPAD_FIRST_VK == 0x60
    assert NUMPAD_LAST_VK == 0x6F
    assert all(NUMPAD_FIRST_VK <= vk <= NUMPAD_LAST_VK for vk in NUMPAD_VK)
