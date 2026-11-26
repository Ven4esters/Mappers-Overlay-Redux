"""Горячие клавиши: маршрутизация, автоповтор и привязки."""

from __future__ import annotations

from map_overlay.application.hotkeys import HotkeyRouter
from map_overlay.domain.actions import DEFAULT_HOTKEYS, Action, hotkey_name
from map_overlay.domain.keynames import (
    VK_F1,
    VK_NUMPAD0,
    VK_NUMPAD2,
    VK_NUMPAD8,
    VK_Y,
    VK_Z,
)
from map_overlay.infrastructure.hotkeys import WindowsHotkeySource, blocks_key

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


def _blocked(*, vk: int = 0x68, is_down: bool = True, **kwargs: object) -> bool:
    options: dict[str, object] = {
        "bound": frozenset({0x68}),
        "bound_ctrl": frozenset(),
        "ctrl_down": False,
        "learning": False,
        "overlay_active": False,
        "swallowed": frozenset(),
    }
    options.update(kwargs)
    return blocks_key(vk=vk, is_down=is_down, **options)  # type: ignore[arg-type]


def test_unbound_key_is_passed_to_the_game() -> None:
    assert _blocked(vk=0x57) is False


def test_bound_key_is_swallowed() -> None:
    assert _blocked() is True


def test_release_is_swallowed_only_after_swallowed_press() -> None:
    assert _blocked(is_down=False, swallowed=frozenset()) is False
    assert _blocked(is_down=False, swallowed=frozenset({0x68})) is True


def test_learning_never_blocks_keys_outside_the_overlay() -> None:
    assert _blocked(vk=0x57, learning=True, overlay_active=False) is False


def test_learning_blocks_any_key_inside_the_overlay() -> None:
    assert _blocked(vk=0x57, learning=True, overlay_active=True) is True


def test_paused_source_keeps_settings_but_reports_state() -> None:
    source = WindowsHotkeySource()
    source.configure(bound_keys={0x60}, learning=False)
    assert source.enabled is True
    source.set_enabled(False)
    assert source.enabled is False
    source.set_enabled(True)
    assert source.enabled is True


def test_autorepeat_from_the_hook_is_not_an_action() -> None:
    router = HotkeyRouter(BINDINGS)
    assert router.handle(VK_NUMPAD8, True, True) is Action.MOVE_FORWARD
    assert router.handle(VK_NUMPAD8, True, False) is None
    assert router.handle(VK_NUMPAD8, True, False) is None
    assert router.handle(VK_NUMPAD8, False, False) is None
    assert router.handle(VK_NUMPAD8, True, True) is Action.MOVE_FORWARD


def test_fresh_press_clears_a_lost_release() -> None:
    router = HotkeyRouter(BINDINGS)
    assert router.handle(VK_NUMPAD8, True, True) is Action.MOVE_FORWARD
    # Отпускание до роутера не дошло: он считает клавишу зажатой.
    assert router.is_pressed(VK_NUMPAD8) is True
    # Настоящее нажатие всё равно срабатывает — иначе клавиша «умерла» бы.
    assert router.handle(VK_NUMPAD8, True, True) is Action.MOVE_FORWARD


def test_reset_forgets_stuck_keys() -> None:
    router = HotkeyRouter(BINDINGS)
    router.handle(VK_NUMPAD8, True, True)
    router.reset()
    assert router.is_pressed(VK_NUMPAD8) is False
    assert router.handle(VK_NUMPAD8, True, None) is Action.MOVE_FORWARD


def test_ctrl_actions_need_ctrl() -> None:
    """Отмена и повтор срабатывают только с Ctrl: обычная Z принадлежит игре."""
    router = HotkeyRouter(DEFAULT_HOTKEYS)
    assert router.handle(VK_Z, True, True, ctrl=True) is Action.UNDO
    assert router.handle(VK_Z, True, True, ctrl=False) is None
    assert router.handle(VK_Y, True, True, ctrl=True) is Action.REDO
    assert router.bound_ctrl_keys == frozenset({VK_Z, VK_Y})


def test_ctrl_keys_are_blocked_only_with_ctrl_and_outside_the_window() -> None:
    """Клавиши отмены забираются у игры только с Ctrl; в окне их обрабатывает окно."""
    assert _blocked(vk=VK_Z, bound={VK_Z}, bound_ctrl={VK_Z}, ctrl_down=True) is True
    assert _blocked(vk=VK_Z, bound={VK_Z}, bound_ctrl={VK_Z}, ctrl_down=False) is False
    assert (
        _blocked(
            vk=VK_Z,
            bound={VK_Z},
            bound_ctrl={VK_Z},
            ctrl_down=True,
            overlay_active=True,
        )
        is False
    )


def test_modifiers_are_not_taken_while_learning() -> None:
    """При записи привязки Ctrl не забирается: иначе Ctrl+Z записался бы как «Ctrl»."""
    assert _blocked(vk=0x11, learning=True, overlay_active=True) is False
    assert _blocked(vk=0x5A, learning=True, overlay_active=True) is True


def test_hotkey_names_show_ctrl_for_undo_and_redo() -> None:
    """В настройках видно, что отмена и повтор — с Ctrl."""
    assert hotkey_name(Action.UNDO, VK_Z) == "Ctrl+Z"
    assert hotkey_name(Action.REDO, VK_Y) == "Ctrl+Y"
    assert hotkey_name(Action.CAPTURE, VK_NUMPAD0) == "Num 0"
    assert hotkey_name(Action.UNDO, None) == "не назначена"
