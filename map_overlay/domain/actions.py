"""Действия, которые можно повесить на горячие клавиши."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from map_overlay.domain.directions import Direction
from map_overlay.domain.keynames import (
    VK_NUMPAD0,
    VK_NUMPAD1,
    VK_NUMPAD2,
    VK_NUMPAD3,
    VK_NUMPAD4,
    VK_NUMPAD5,
    VK_NUMPAD6,
    VK_NUMPAD7,
    VK_NUMPAD8,
    VK_NUMPAD9,
)


class Action(StrEnum):
    """Действие оверлея, привязанное к клавише."""

    CAPTURE = "capture"
    CONFIRM = "confirm"
    MOVE_FORWARD = "move_forward"
    MOVE_BACK = "move_back"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    MOVE_FORWARD_LEFT = "move_forward_left"
    MOVE_FORWARD_RIGHT = "move_forward_right"
    MOVE_BACK_LEFT = "move_back_left"
    MOVE_BACK_RIGHT = "move_back_right"

    @property
    def label(self) -> str:
        """Подпись действия в интерфейсе."""
        return _LABELS[self]

    @property
    def direction(self) -> Direction | None:
        """Направление сдвига, если действие двигает предмет."""
        return _DIRECTIONS.get(self)


_DIRECTIONS: Final[dict[Action, Direction]] = {
    Action.MOVE_FORWARD: Direction.FORWARD,
    Action.MOVE_BACK: Direction.BACK,
    Action.MOVE_LEFT: Direction.LEFT,
    Action.MOVE_RIGHT: Direction.RIGHT,
    Action.MOVE_FORWARD_LEFT: Direction.FORWARD_LEFT,
    Action.MOVE_FORWARD_RIGHT: Direction.FORWARD_RIGHT,
    Action.MOVE_BACK_LEFT: Direction.BACK_LEFT,
    Action.MOVE_BACK_RIGHT: Direction.BACK_RIGHT,
}

_LABELS: Final[dict[Action, str]] = {
    Action.CAPTURE: "Считать координаты",
    Action.CONFIRM: "Сохранить F",
    Action.MOVE_FORWARD: "Вперёд",
    Action.MOVE_BACK: "Назад",
    Action.MOVE_LEFT: "Влево",
    Action.MOVE_RIGHT: "Вправо",
    Action.MOVE_FORWARD_LEFT: "Вперёд-влево",
    Action.MOVE_FORWARD_RIGHT: "Вперёд-вправо",
    Action.MOVE_BACK_LEFT: "Назад-влево",
    Action.MOVE_BACK_RIGHT: "Назад-вправо",
}

ACTION_ORDER: Final[tuple[Action, ...]] = (
    Action.CAPTURE,
    Action.CONFIRM,
    Action.MOVE_FORWARD,
    Action.MOVE_FORWARD_LEFT,
    Action.MOVE_FORWARD_RIGHT,
    Action.MOVE_BACK,
    Action.MOVE_BACK_LEFT,
    Action.MOVE_BACK_RIGHT,
    Action.MOVE_LEFT,
    Action.MOVE_RIGHT,
)


DEFAULT_HOTKEYS: Final[dict[Action, int | None]] = {
    Action.CAPTURE: VK_NUMPAD0,
    Action.CONFIRM: VK_NUMPAD5,
    Action.MOVE_FORWARD: VK_NUMPAD8,
    Action.MOVE_FORWARD_LEFT: VK_NUMPAD7,
    Action.MOVE_FORWARD_RIGHT: VK_NUMPAD9,
    Action.MOVE_BACK: VK_NUMPAD2,
    Action.MOVE_BACK_LEFT: VK_NUMPAD1,
    Action.MOVE_BACK_RIGHT: VK_NUMPAD3,
    Action.MOVE_LEFT: VK_NUMPAD4,
    Action.MOVE_RIGHT: VK_NUMPAD6,
}
# Клавиши по умолчанию: цифровой блок при включённом NumLock.
