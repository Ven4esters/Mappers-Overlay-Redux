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


class _FakeHook:
    def __init__(self, bindings):
        self.bindings = list(bindings)
        self.installed = True

    def set_bindings(self, bindings):
        self.bindings = list(bindings)


def test_suspend_and_resume_toggle_bindings_roundtrip() -> None:
    from app.hotkeys import HotkeyManager, build_bindings

    manager = HotkeyManager()
    manager._capture_combo = "Print"
    original = build_bindings("Print")
    fake = _FakeHook(original)
    manager._hook = fake  # inject — no Win32 in the sandbox

    manager.suspend()
    assert fake.bindings == []
    assert manager.suspended is True
    # idempotent — second call must not raise or double-unregister
    manager.suspend()
    assert manager.suspended is True

    assert manager.resume() == []
    assert [b.action for b in fake.bindings] == [b.action for b in original]
    assert manager.suspended is False
    # resuming twice is a no-op
    assert manager.resume() == []


def test_suspend_clears_match_output() -> None:
    bindings = _bindings()
    hook = LowLevelKeyboardHook(lambda a: None, bindings)
    assert match_combo(hook.bindings, 0, 0x78) == "overlay"
    hook.set_bindings([])
    assert match_combo(hook.bindings, 0, 0x78) is None


def test_overlay_keys_pass_through_while_active() -> None:
    from app.low_level_hook import LowLevelKeyboardHook

    fired: list[str] = []
    hook = LowLevelKeyboardHook(fired.append, _bindings())
    assert hook.handle_key_event(0x0D, 0) is False  # Enter passes through when overlay is off

    hook.set_overlay_active(True)
    assert hook.handle_key_event(0x0D, 0) is True   # Enter
    assert hook.handle_key_event(0x1B, 0) is True   # Escape
    assert hook.handle_key_event(0x32, 0) is True   # '2'
    assert hook.handle_key_event(0x62, 0) is True   # Numpad2
    assert hook.handle_key_event(0x39, 0) is False  # '9' is not an overlay key
    assert hook.handle_key_event(0x0D, 0, injected=True) is False  # injected stays untouched
    # built-in combos still resolve alongside overlay keys
    assert hook.handle_key_event(0x2C, 0) is True   # PrtSc -> overlay action
    hook.set_overlay_active(False)
    assert hook.handle_key_event(0x0D, 0) is False

    assert fired == ["overlay:enter", "overlay:escape", "overlay:2", "overlay:2", "overlay"]


def test_force_foreground_non_windows_is_false() -> None:
    import sys

    from app.low_level_hook import force_foreground

    if not sys.platform.startswith("win"):
        assert force_foreground(0) is False
        assert force_foreground(12345) is False


def test_queue_store_roundtrip(tmp_path, monkeypatch) -> None:
    import app.cache
    import app.queue_store as qs

    monkeypatch.setattr(app.cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(qs, "CACHE_DIR", tmp_path)

    name1 = qs.store_shot(b"fake-png-bytes", "shot_1.png")
    name2 = qs.store_shot(b"fake-png-bytes", "shot_1.png")
    assert name1 == name2                      # content-addressed dedup
    assert (tmp_path / "shots" / name1).is_file()

    entry = qs.make_entry("id-1", "shot_1.png", name1, "image/png", checked=True)
    qs.write_entries([entry])
    loaded = qs.load_entries()
    assert loaded == [entry]

    restored = qs.restore_entries()
    assert len(restored) == 1 and restored[0]["file"] == name1

    # cached file gone -> entry is dropped, not restored
    qs.shot_path(name1).unlink()
    assert qs.restore_entries() == []

    # corrupt index -> empty queue, no crash
    qs.index_path().write_text("{ not json !", encoding="utf-8")
    assert qs.load_entries() == []


def test_queue_store_empty_by_default(tmp_path, monkeypatch) -> None:
    import app.queue_store as qs

    monkeypatch.setattr(qs, "CACHE_DIR", tmp_path)
    assert qs.load_entries() == []
    assert qs.restore_entries() == []
