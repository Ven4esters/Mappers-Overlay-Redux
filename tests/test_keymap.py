"""Клавиши Numpad: разбор нажатий и их действие в окне."""

from __future__ import annotations

import pytest
from lsp_overlay.domain.directions import Direction
from lsp_overlay.ui.keymap import NumpadIntent, numpad_action
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

KEYPAD = Qt.KeyboardModifier.KeypadModifier
NUMBERS: tuple[tuple[int, Direction], ...] = (
    (Qt.Key.Key_8, Direction.NORTH),
    (Qt.Key.Key_2, Direction.SOUTH),
    (Qt.Key.Key_4, Direction.WEST),
    (Qt.Key.Key_6, Direction.EAST),
    (Qt.Key.Key_7, Direction.NORTH_WEST),
    (Qt.Key.Key_9, Direction.NORTH_EAST),
    (Qt.Key.Key_1, Direction.SOUTH_WEST),
    (Qt.Key.Key_3, Direction.SOUTH_EAST),
)


@pytest.mark.parametrize(("key", "direction"), NUMBERS)
def test_numpad_digits_move_in_eight_directions(key: int, direction: Direction) -> None:
    action = numpad_action(key, KEYPAD)
    assert action is not None
    assert action.intent is NumpadIntent.MOVE
    assert action.direction is direction


def test_numpad_commands() -> None:
    assert numpad_action(Qt.Key.Key_5, KEYPAD) == numpad_action(Qt.Key.Key_5, KEYPAD)
    assert numpad_action(Qt.Key.Key_5, KEYPAD).intent is NumpadIntent.COMMIT  # type: ignore[union-attr]
    assert numpad_action(Qt.Key.Key_0, KEYPAD).intent is NumpadIntent.CAPTURE  # type: ignore[union-attr]
    assert numpad_action(Qt.Key.Key_Enter, KEYPAD).intent is NumpadIntent.APPLY  # type: ignore[union-attr]
    assert numpad_action(Qt.Key.Key_Plus, KEYPAD).intent is NumpadIntent.STEP_UP  # type: ignore[union-attr]
    assert numpad_action(Qt.Key.Key_Minus, KEYPAD).intent is NumpadIntent.STEP_DOWN  # type: ignore[union-attr]


def test_plain_digits_and_arrows_are_ignored() -> None:
    assert numpad_action(Qt.Key.Key_8, Qt.KeyboardModifier.NoModifier) is None
    assert numpad_action(Qt.Key.Key_Up, KEYPAD) is None
    assert numpad_action(Qt.Key.Key_A, KEYPAD) is None


def press_key(widget: object, key: int, modifiers: Qt.KeyboardModifier = KEYPAD) -> None:
    """Отправляет нажатие клавиши в виджет так, как это сделал бы пользователь."""
    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
    widget.keyPressEvent(event)  # type: ignore[attr-defined]
