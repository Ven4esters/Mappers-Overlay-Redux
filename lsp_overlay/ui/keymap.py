"""Клавиши Numpad: движение и быстрые команды (стрелки в игре заняты).

Оверлей не перехватывает клавиши глобально: события приходят, когда окно оверлея
в фокусе. Numpad выбран потому, что стрелки и цифровой ряд заняты панелью LSP и игрой.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import Qt

from lsp_overlay.domain.directions import Direction


class NumpadIntent(StrEnum):
    """Что означает нажатая клавиша Numpad."""

    MOVE = "move"
    CAPTURE = "capture"
    APPLY = "apply"
    COMMIT = "commit"
    STEP_UP = "step_up"
    STEP_DOWN = "step_down"


@dataclass(frozen=True, slots=True)
class NumpadAction:
    """Разобранное нажатие: намерение и (для движения) направление."""

    intent: NumpadIntent
    direction: Direction | None = None


MOVE_KEYS: dict[int, Direction] = {
    Qt.Key.Key_8: Direction.NORTH,
    Qt.Key.Key_2: Direction.SOUTH,
    Qt.Key.Key_4: Direction.WEST,
    Qt.Key.Key_6: Direction.EAST,
    Qt.Key.Key_7: Direction.NORTH_WEST,
    Qt.Key.Key_9: Direction.NORTH_EAST,
    Qt.Key.Key_1: Direction.SOUTH_WEST,
    Qt.Key.Key_3: Direction.SOUTH_EAST,
}

COMMAND_KEYS: dict[int, NumpadIntent] = {
    Qt.Key.Key_0: NumpadIntent.CAPTURE,
    Qt.Key.Key_5: NumpadIntent.COMMIT,
    Qt.Key.Key_Enter: NumpadIntent.APPLY,
    Qt.Key.Key_Plus: NumpadIntent.STEP_UP,
    Qt.Key.Key_Minus: NumpadIntent.STEP_DOWN,
}

NUMPAD_HINT = (
    "Numpad: 8/2/4/6 и 7/9/1/3 — движение, 0 — «Считать», 5 — «Сохранить F», "
    "Enter — применить, +/− — шаг. NumLock должен быть включён."
)


def numpad_action(key: int, modifiers: Qt.KeyboardModifier) -> NumpadAction | None:
    """Разбирает нажатие: ``None``, если это не Numpad или клавиша не наша."""
    if not modifiers & Qt.KeyboardModifier.KeypadModifier:
        return None
    direction = MOVE_KEYS.get(key)
    if direction is not None:
        return NumpadAction(intent=NumpadIntent.MOVE, direction=direction)
    intent = COMMAND_KEYS.get(key)
    if intent is not None:
        return NumpadAction(intent=intent)
    return None
