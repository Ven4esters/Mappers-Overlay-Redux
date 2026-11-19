"""Parse/normalize human-hotkeys like ``Ctrl+Shift+Q`` — pure stdlib, no Qt.
Разбор и нормализация хоткеев вида ``Ctrl+Shift+Q`` — без Qt, только stdlib.

Canonical form: modifiers in the fixed order Ctrl, Shift, Alt, Meta, then the
base key. Used both for Win32 RegisterHotKey (needs VK codes) and as the
storage format in ``AppSettings.capture_hotkey``.
Каноническая форма: модификаторы в порядке Ctrl, Shift, Alt, Meta, затем
базовая клавиша. Используется и для Win32 RegisterHotKey (нужны VK-коды),
и как формат хранения ``AppSettings.capture_hotkey``.
"""

from __future__ import annotations

MOD_SHIFT, MOD_CONTROL, MOD_ALT, MOD_WIN = 0x0004, 0x0002, 0x0001, 0x0008

# (display name, windows MOD flag) in canonical order
_MODIFIERS: list[tuple[str, int]] = [
    ("Ctrl", MOD_CONTROL),
    ("Shift", MOD_SHIFT),
    ("Alt", MOD_ALT),
    ("Meta", MOD_WIN),
]
_MOD_BY_LOWER = {name.lower(): name for name, _ in _MODIFIERS}
_MOD_FLAGS = dict(_MODIFIERS)

_LETTERS = {chr(ord("A") + i): 0x41 + i for i in range(26)}
_DIGITS = {str(i): 0x30 + i for i in range(10)}
_FKEYS = {f"F{n}": 0x70 + n - 1 for n in range(1, 25)}
_SPECIALS = {
    "Print": 0x2C, "ScrollLock": 0x91, "Pause": 0x13, "NumLock": 0x90,
    "Space": 0x20, "Tab": 0x09, "Escape": 0x1B, "Backspace": 0x08,
    "Return": 0x0D, "Insert": 0x2D, "Delete": 0x2E,
    "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
}
VK_TABLE: dict[str, int] = {**_LETTERS, **_DIGITS, **_FKEYS, **_SPECIALS}

_BASE_ALIASES = {
    "printscreen": "Print", "prtsc": "Print", "print screen": "Print",
    "snapshot": "Print", "prtscn": "Print",
    "scroll": "ScrollLock", "scrolllock": "ScrollLock", "pausebreak": "Pause",
    "esc": "Escape", "backspace": "Backspace", "del": "Delete", "ins": "Insert",
    "enter": "Return", "pgup": "PageUp", "pgdn": "PageDown",
    "pageup": "PageUp", "pagedown": "PageDown", "arrowleft": "Left",
    "arrowup": "Up", "arrowright": "Right", "arrowdown": "Down",
    "spacebar": "Space",
}
_BASE_BY_LOWER = {name.lower(): name for name in VK_TABLE}

_MOD_ALIASES = {
    "ctrl": "Ctrl", "control": "Ctrl",
    "shift": "Shift",
    "alt": "Alt", "option": "Alt",
    "meta": "Meta", "win": "Meta", "super": "Meta", "windows": "Meta",
}

DEFAULT_HOTKEY = "Print"
RESERVED = frozenset({"Ctrl+Shift+S", "Ctrl+Shift+R"})  # built-in full screen / region


def _canon_base(token: str) -> str | None:
    low = token.lower()
    if low in _BASE_BY_LOWER:
        return _BASE_BY_LOWER[low]
    if low in _BASE_ALIASES:
        return _BASE_ALIASES[low]
    return None


def normalize_hotkey(text: str) -> str | None:
    """Canonicalize any spelling of a combo (case-insensitive) or return None.
    Канонизировать хоткей (без учёта регистра) либо вернуть None."""
    if not text:
        return None
    tokens = [t.strip() for t in text.split("+") if t.strip()]
    if not tokens:
        return None
    base = _canon_base(tokens[-1])
    if base is None:
        return None
    seen: list[str] = []
    for raw in tokens[:-1]:
        mod = _MOD_ALIASES.get(raw.lower())
        if mod is None or mod in seen:   # unknown token or duplicate modifier
            return None
        seen.append(mod)
    parts = [name for name, _mod in _MODIFIERS if name in seen] + [base]
    return "+".join(parts)


def display_hotkey(text: str) -> str:
    """Canonical combo for display; falls back to the raw text. / Канон для показа."""
    return normalize_hotkey(text) or text


def to_windows(text: str) -> tuple[int, int] | None:
    """(RegisterHotKey modifier flags, virtual-key code) or None when invalid.
    (флаги модификаторов RegisterHotKey, виртуальный код) или None."""
    norm = normalize_hotkey(text)
    if norm is None:
        return None
    tokens = norm.split("+")
    mods = 0
    for token in tokens[:-1]:
        mods |= _MOD_FLAGS[token]
    return mods, VK_TABLE[tokens[-1]]


def is_reserved(text: str) -> bool:
    """True when the combo clashes with built-in Ctrl+Shift+S / Ctrl+Shift+R.
    True, если комбинация занята встроенными Ctrl+Shift+S / Ctrl+Shift+R."""
    norm = normalize_hotkey(text)
    return norm in RESERVED if norm else False
