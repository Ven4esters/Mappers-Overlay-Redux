"""Виртуальные коды клавиш Windows и их подписи."""

from __future__ import annotations

from typing import Final

VK_TAB: Final = 0x09
VK_SHIFT: Final = 0x10
VK_CONTROL: Final = 0x11
VK_ENTER: Final = 0x0D
VK_ESCAPE: Final = 0x1B
VK_SPACE: Final = 0x20
#: Alt — переключатель режима высоты; сам по себе не перехватывается.
VK_MENU: Final = 0x12
VK_LEFT: Final = 0x25
VK_UP: Final = 0x26
VK_RIGHT: Final = 0x27
VK_DOWN: Final = 0x28
VK_NUMPAD0: Final = 0x60
VK_NUMPAD1: Final = 0x61
VK_NUMPAD2: Final = 0x62
VK_NUMPAD3: Final = 0x63
VK_NUMPAD4: Final = 0x64
VK_NUMPAD5: Final = 0x65
VK_NUMPAD6: Final = 0x66
VK_NUMPAD7: Final = 0x67
VK_NUMPAD8: Final = 0x68
VK_NUMPAD9: Final = 0x69
VK_MULTIPLY: Final = 0x6A
VK_ADD: Final = 0x6B
VK_SUBTRACT: Final = 0x6D
VK_DECIMAL: Final = 0x6E
VK_DIVIDE: Final = 0x6F
VK_F1: Final = 0x70
VK_NUMLOCK: Final = 0x90

#: Низкоуровневый хук присылает клавишу со стороной: ``VK_LMENU`` вместо ``VK_MENU``.
_SIDE_VARIANTS: Final[dict[int, int]] = {
    0xA0: VK_SHIFT,
    0xA1: VK_SHIFT,
    0xA2: VK_CONTROL,
    0xA3: VK_CONTROL,
    0xA4: VK_MENU,
    0xA5: VK_MENU,
}

#: Клавиши, которые обычно заняты в игре: их перехват лишит игру управления.
COMMON_GAME_KEYS: Final = frozenset(
    {
        0x57,  # W
        0x41,  # A
        0x53,  # S
        0x44,  # D
        0x45,  # E
        0x46,  # F
        0x51,  # Q
        0x52,  # R
        0x43,  # C
        VK_SPACE,
        0x10,  # Shift
        0x11,  # Ctrl
        VK_TAB,
        VK_ESCAPE,
    }
)

MIN_VK: Final = 0x01
MAX_VK: Final = 0xFE
UNBOUND: Final = None

_SPECIAL_NAMES: Final[dict[int, str]] = {
    VK_TAB: "Tab",
    VK_ENTER: "Enter",
    VK_ESCAPE: "Esc",
    VK_SPACE: "Пробел",
    VK_LEFT: "←",
    VK_UP: "↑",
    VK_RIGHT: "→",
    VK_DOWN: "↓",
    VK_MULTIPLY: "Num *",
    VK_ADD: "Num +",
    VK_SUBTRACT: "Num −",
    VK_DECIMAL: "Num .",
    VK_DIVIDE: "Num /",
    VK_NUMLOCK: "NumLock",
    VK_MENU: "Alt",
    0x10: "Shift",
    0x11: "Ctrl",
}
_SPECIAL_NAMES.update({VK_NUMPAD0 + digit: f"Num {digit}" for digit in range(10)})
_SPECIAL_NAMES.update({VK_F1 + index: f"F{index + 1}" for index in range(12)})
_SPECIAL_NAMES.update({0x41 + index: chr(ord("A") + index) for index in range(26)})


def generic_vk(vk: int) -> int:
    """Свести клавишу со «стороной» к общему коду.

    Хук клавиатуры сообщает конкретную клавишу: левый Alt приходит как ``VK_LMENU``
    (``0xA4``), а не как ``VK_MENU`` (``0x12``). Без сведения не работали бы ни
    переключатель режима высоты на Alt, ни горячие клавиши на Shift и Ctrl.
    """
    return _SIDE_VARIANTS.get(vk, vk)


def key_name(vk: int | None) -> str:
    """Человеческое имя клавиши по виртуальному коду."""
    if vk is None:
        return "не назначена"
    return _SPECIAL_NAMES.get(vk, f"VK {vk:02X}")


def is_numpad(vk: int | None) -> bool:
    """Относится ли клавиша к цифровому блоку."""
    return vk is not None and VK_NUMPAD0 <= vk <= VK_DIVIDE


def is_valid_vk(vk: object) -> bool:
    """Подходит ли код для привязки."""
    return isinstance(vk, int) and not isinstance(vk, bool) and MIN_VK <= vk <= MAX_VK
