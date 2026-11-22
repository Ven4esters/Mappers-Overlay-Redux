"""Горячие клавиши: маршрутизация, автоповтор и привязки."""

from __future__ import annotations

from map_overlay.application.hotkeys import HotkeyRouter
from map_overlay.domain.actions import DEFAULT_HOTKEYS, Action
from map_overlay.domain.keynames import (
    VK_F1,
    VK_NUMPAD0,
    VK_NUMPAD2,
    VK_NUMPAD8,
)

BINDINGS = {Action.CAPTURE: VK_NUMPAD0, Action.MOVE_FORWARD: VK_NUMPAD8}


def test_bound_key_returns_action() -> None:
    router = HotkeyRouter(BINDINGS)
    assert router.handle(VK_NUMPAD0, True) is Action.CAPTURE
    assert router.handle(VK_NUMPAD8, True) is Action.MOVE_FORWARD


def test_unknown_key_does_nothing() -> None:
    router = HotkeyRouter(BINDINGS)
    assert router.handle(VK_NUMPAD2, True) is None


def test_repeat_is_ignored_until_key_release() -> None:
    router = HotkeyRouter(BINDINGS)
    assert router.handle(VK_NUMPAD8, True) is Action.MOVE_FORWARD
    assert router.handle(VK_NUMPAD8, True) is None
    assert router.handle(VK_NUMPAD8, True) is None
    assert router.handle(VK_NUMPAD8, False) is None
    assert router.handle(VK_NUMPAD8, True) is Action.MOVE_FORWARD


def test_key_release_is_not_an_action() -> None:
    router = HotkeyRouter(BINDINGS)
    assert router.handle(VK_NUMPAD0, False) is None


def test_unbound_key_is_not_a_pressed_state() -> None:
    router = HotkeyRouter(BINDINGS)
    router.handle(VK_F1, True)
    assert router.bound_keys == frozenset(BINDINGS.values())


def test_rebinding_changes_the_map() -> None:
    router = HotkeyRouter(BINDINGS)
    router.bind({Action.CAPTURE: VK_F1})
    assert router.handle(VK_NUMPAD0, True) is None
    assert router.handle(VK_F1, True) is Action.CAPTURE
    assert router.bound_keys == frozenset({VK_F1})


def test_unbound_action_is_skipped() -> None:
    router = HotkeyRouter({Action.CAPTURE: None})
    assert router.bound_keys == frozenset()
    assert router.handle(VK_NUMPAD0, True) is None


def test_defaults_use_numpad_and_are_unique() -> None:
    keys = [key for key in DEFAULT_HOTKEYS.values() if key is not None]
    assert len(keys) == len(set(keys)) == len(Action)
