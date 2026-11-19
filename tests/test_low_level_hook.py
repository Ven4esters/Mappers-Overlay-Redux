"""Low-level hook tests (platform-independent logic). / Тесты логики хука."""

from __future__ import annotations

from app.hotkey_parse import to_windows
from app.low_level_hook import (
    MOD_CONTROL, MOD_SHIFT, MOD_ALT, MOD_WIN, ComboBinding, LowLevelKeyboardHook,
    match_combo,
)


def _bindings() -> list[ComboBinding]:
    bindings = []
    for combo, action in (("Ctrl+Shift+S", "fullscreen"),
                          ("Ctrl+Shift+R", "region"),
                          ("F9", "overlay"),
                          ("Print", "overlay")):
        parsed = to_windows(combo)
        assert parsed is not None
        bindings.append(ComboBinding(*parsed, action))
    return bindings


def test_match_exact_mods_only() -> None:
    bindings = _bindings()
    cs_s = to_windows("Ctrl+Shift+S")
    assert match_combo(bindings, cs_s[0], cs_s[1]) == "fullscreen"
    # extra modifier → no match (Ctrl+Shift+Alt+S is a different combo)
    assert match_combo(bindings, cs_s[0] | MOD_ALT, cs_s[1]) is None
    # right keys but missing modifier → no match
    assert match_combo(bindings, MOD_CONTROL, cs_s[1]) is None
    # F9 alone matches the overlay
    assert match_combo(bindings, 0, 0x78) == "overlay"


def test_match_returns_none_for_unbound() -> None:
    assert match_combo(_bindings(), 0, 0x41) is None  # plain A
    assert match_combo(_bindings(), MOD_WIN, 0x2C) is None  # Win+PrtSc is unbound


def test_handler_swallows_only_bound_combos() -> None:
    fired: list[str] = []
    hook = LowLevelKeyboardHook(fired.append, _bindings())
    assert hook.handle_key_event(0x78, 0) is True       # F9 → overlay swallowed
    assert fired == ["overlay"]
    assert hook.handle_key_event(0x53, MOD_CONTROL | MOD_SHIFT) is True  # Ctrl+Shift+S
    assert fired == ["overlay", "fullscreen"]
    assert hook.handle_key_event(0x41, 0) is False     # unbound passes through
    assert hook.handle_key_event(0x2C, 0, injected=True) is False  # injected ignored
    assert fired == ["overlay", "fullscreen"]


def test_handler_exception_still_swallows_and_logs() -> None:
    def boom(action: str) -> None:
        raise RuntimeError("boom")

    hook = LowLevelKeyboardHook(boom, _bindings())
    assert hook.handle_key_event(0x78, 0) is True      # exception logged, combo swallowed


def test_build_bindings_skips_and_dedupes() -> None:
    from app.hotkeys import build_bindings

    bindings = build_bindings("Ctrl+Shift+Q")
    actions = [b.action for b in bindings]
    assert actions.count("overlay") == 1 and actions.count("fullscreen") == 1
    # a bogus config value is skipped, built-ins survive
    bindings = build_bindings("not-a-key")
    assert [b.action for b in bindings] == ["fullscreen", "region"]
    # user jammed the capture combo onto a built-in: first binding wins
    bindings = build_bindings("Ctrl+Shift+S")
    assert bindings[0].action == "fullscreen"
    assert bindings[-1].action == "fullscreen" or len(bindings) == 2
