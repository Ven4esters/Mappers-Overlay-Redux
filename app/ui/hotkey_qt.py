"""Qt glue for capture hotkeys (UI layer only). / Qt-склейка хоткеев снимка.

Builds a ``QKeySequence`` from our canonical combo text. Written defensively:
every Qt symbol is resolved lazily, so a missing/relocated class (as happened
with ``QKeyCombination`` in ``QtGui`` vs ``QtCore`` in different PySide6
versions) never breaks the app at import time — worst case the in-window
shortcut stays unbound while the global hotkey keeps working.
Строит ``QKeySequence`` из канонического хоткея. Все Qt-символы резолвятся
лениво: отсутствие/переезд класса никогда не роняет приложение при импорте —
в худшем случае не сработает внутриоконный хоткей (глобальный останется).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from app.hotkey_parse import normalize_hotkey


def _enum_member(flat_map: dict[str, str]) -> dict:
    """Resolve ``Key_X`` / ``KeyboardModifier_X`` from either enum namespace."""
    resolved: dict = {}
    namespaces = [getattr(Qt, "Key", None), getattr(Qt, "KeyboardModifier", None), Qt]
    for token, member in flat_map.items():
        for ns in namespaces:
            if ns is None:
                continue
            value = getattr(ns, member, None)
            if value is not None:
                resolved[token] = value
                break
    return resolved


_BASE_TOKENS = {
    **{chr(ord("A") + i): f"Key_{chr(ord('A') + i)}" for i in range(26)},
    **{str(i): f"Key_{i}" for i in range(10)},
    **{f"F{n}": f"Key_F{n}" for n in range(1, 25)},
    "Print": "Key_Print", "ScrollLock": "Key_ScrollLock",
    "Pause": "Key_Pause", "NumLock": "Key_NumLock",
    "Space": "Key_Space", "Tab": "Key_Tab", "Escape": "Key_Escape",
    "Backspace": "Key_Backspace", "Return": "Key_Return",
    "Insert": "Key_Insert", "Delete": "Key_Delete",
    "Home": "Key_Home", "End": "Key_End",
    "PageUp": "Key_PageUp", "PageDown": "Key_PageDown",
    "Left": "Key_Left", "Up": "Key_Up", "Right": "Key_Right", "Down": "Key_Down",
}
_MOD_TOKENS = {"Ctrl": "ControlModifier", "Shift": "ShiftModifier",
               "Alt": "AltModifier", "Meta": "MetaModifier"}
# Qt portable-text aliases for the last-resort string path
_PORTABLE_ALIASES = {"Escape": "Esc", "PageUp": "PgUp", "PageDown": "PgDown"}


def _key_combination_class():
    try:
        from PySide6 import QtCore

        cls = getattr(QtCore, "QKeyCombination", None)
        if cls is not None:
            return cls
    except Exception:  # noqa: BLE001 — defensive: version-dependent layout
        pass
    try:
        from PySide6 import QtGui

        return getattr(QtGui, "QKeyCombination", None)
    except Exception:  # noqa: BLE001
        return None


def _no_modifier():
    for ns in (getattr(Qt, "KeyboardModifier", None), getattr(Qt, "Modifier", None), Qt):
        if ns is None:
            continue
        value = getattr(ns, "NoModifier", None)
        if value is not None:
            return value
    return 0  # flags are int-compatible; 0 == NoModifier


def _modifiers(tokens: list[str]):
    if not tokens:
        return _no_modifier()
    resolved = _enum_member(_MOD_TOKENS)
    combo = _no_modifier()
    for token in tokens:
        value = resolved.get(token)
        if value is None:
            return None
        combo = combo | value
    return combo


def build_shortcut_sequence(combo: str):
    """Return a QKeySequence for ``combo`` or None when unsupported/unknown."""
    norm = normalize_hotkey(combo)
    if not norm:
        return None
    tokens = norm.split("+")
    base = tokens[-1]
    modifier_tokens = tokens[:-1]
    key = _enum_member(_BASE_TOKENS).get(base)
    mods = _modifiers(modifier_tokens)

    if key is not None and mods is not None:
        combo_cls = _key_combination_class()
        if combo_cls is not None:
            try:
                return QKeySequence(combo_cls(mods, key))
            except Exception:  # noqa: BLE001 — fall through to bit packing
                pass
            try:
                return QKeySequence(combo_cls.fromCombined(int(mods) | int(key)))
            except Exception:  # noqa: BLE001 — fall through to string
                pass

    # portable-string last resort (standard names parse in every Qt)
    candidate = "+".join(
        [*modifier_tokens, _PORTABLE_ALIASES.get(base, base)])
    sequence = QKeySequence(candidate)
    return sequence if not sequence.isEmpty() else None
