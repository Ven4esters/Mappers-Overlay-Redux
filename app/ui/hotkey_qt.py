"""Qt glue for capture hotkeys (UI layer only). / Qt-склейка хоткеев снимка.

Builds a ``QKeySequence`` from our canonical combo text. Kept separate so the
pure parsing layer (``app.hotkey_parse``) stays Qt-free and unit-testable.
Строит ``QKeySequence`` из канонического хоткея; парсинг живёт отдельно,
без Qt — чтобы его можно было тестировать без GUI.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyCombination, QKeySequence

from app.hotkey_parse import normalize_hotkey

_MOD_FLAGS: dict[str, "Qt.KeyboardModifier"] = {}
for _attr, _name in (("ControlModifier", "Ctrl"),
                     ("ShiftModifier", "Shift"),
                     ("AltModifier", "Alt"),
                     ("MetaModifier", "Meta")):
    _MOD_FLAGS[_name] = getattr(Qt.KeyboardModifier, _attr)

_BASE_KEYS: dict[str, "Qt.Key"] = {}
for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _BASE_KEYS[_letter] = getattr(Qt.Key, f"Key_{_letter}")
for _digit in "0123456789":
    _BASE_KEYS[_digit] = getattr(Qt.Key, f"Key_{_digit}")
for _n in range(1, 25):
    _BASE_KEYS[f"F{_n}"] = getattr(Qt.Key, f"Key_F{_n}")
_BASE_KEYS.update({
    "Print": Qt.Key.Key_Print, "ScrollLock": Qt.Key.Key_ScrollLock,
    "Pause": Qt.Key.Key_Pause, "NumLock": Qt.Key.Key_NumLock,
    "Space": Qt.Key.Key_Space, "Tab": Qt.Key.Key_Tab, "Escape": Qt.Key.Key_Escape,
    "Backspace": Qt.Key.Key_Backspace, "Return": Qt.Key.Key_Return,
    "Insert": Qt.Key.Key_Insert, "Delete": Qt.Key.Key_Delete,
    "Home": Qt.Key.Key_Home, "End": Qt.Key.Key_End,
    "PageUp": Qt.Key.Key_PageUp, "PageDown": Qt.Key.Key_PageDown,
    "Left": Qt.Key.Key_Left, "Up": Qt.Key.Key_Up,
    "Right": Qt.Key.Key_Right, "Down": Qt.Key.Key_Down,
})


def build_shortcut_sequence(combo: str):
    """Return a QKeySequence for ``combo`` or None when unsupported/unknown.
    Вернуть QKeySequence для ``combo`` либо None."""
    norm = normalize_hotkey(combo)
    if not norm:
        return None
    key_limit = None
    mods = Qt.KeyboardModifier.NoModifier
    for token in norm.split("+"):
        if token in _MOD_FLAGS:
            mods |= _MOD_FLAGS[token]
            continue
        key = _BASE_KEYS.get(token)
        if key is None:
            return None
        key_limit = key
    if key_limit is None:
        return None
    # Qt6 path: QKeyCombination(KeyboardModifiers, Key) → QKeySequence
    try:
        return QKeySequence(QKeyCombination(mods, key_limit))
    except Exception:  # noqa: BLE001 — older PySide6: pack bits manually
        try:
            return QKeySequence(int(mods) | int(key_limit))
        except Exception:  # noqa: BLE001 — last resort: portable string
            sequence = QKeySequence(norm)
            return sequence if not sequence.isEmpty() else None
