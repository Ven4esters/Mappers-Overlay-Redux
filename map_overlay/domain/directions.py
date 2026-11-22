"""Восемь направлений сдвига в плоскости.

Конвенция задана пользователем для нулевых углов (см. ``docs/adr/0002-direction-convention.md``):

* вперёд — ``X`` в плюс, назад — ``X`` в минус;
* влево — ``Y`` в плюс, вправо — ``Y`` в минус;
* диагонали — комбинация этих правил.

Поэтому каждая сторона света — это единичный вектор в мире, а не «плюс/минус
по произвольной оси».
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Direction(StrEnum):
    """Направление сдвига предмета."""

    FORWARD = "forward"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    FORWARD_LEFT = "forward_left"
    FORWARD_RIGHT = "forward_right"
    BACK_LEFT = "back_left"
    BACK_RIGHT = "back_right"

    @property
    def axes(self) -> tuple[int, int]:
        """Единичный вектор ``(dx, dy)``: куда именно меняются ``X`` и ``Y``."""
        return _AXES[self]

    @property
    def label(self) -> str:
        """Название для интерфейса и журнала."""
        return _TITLES[self]

    @property
    def glyph(self) -> str:
        """Символ на кнопке."""
        return _GLYPHS[self]

    @property
    def is_diagonal(self) -> bool:
        """Двигает ли направление обе координаты сразу."""
        return 0 not in self.axes


_AXES: Final[dict[Direction, tuple[int, int]]] = {
    Direction.FORWARD: (1, 0),
    Direction.BACK: (-1, 0),
    Direction.LEFT: (0, 1),
    Direction.RIGHT: (0, -1),
    Direction.FORWARD_LEFT: (1, 1),
    Direction.FORWARD_RIGHT: (1, -1),
    Direction.BACK_LEFT: (-1, 1),
    Direction.BACK_RIGHT: (-1, -1),
}

_TITLES: Final[dict[Direction, str]] = {
    Direction.FORWARD: "Вперёд",
    Direction.BACK: "Назад",
    Direction.LEFT: "Влево",
    Direction.RIGHT: "Вправо",
    Direction.FORWARD_LEFT: "Вперёд-влево",
    Direction.FORWARD_RIGHT: "Вперёд-вправо",
    Direction.BACK_LEFT: "Назад-влево",
    Direction.BACK_RIGHT: "Назад-вправо",
}

_GLYPHS: Final[dict[Direction, str]] = {
    Direction.FORWARD: "\u2191",
    Direction.BACK: "\u2193",
    Direction.LEFT: "\u2190",
    Direction.RIGHT: "\u2192",
    Direction.FORWARD_LEFT: "\u2196",
    Direction.FORWARD_RIGHT: "\u2197",
    Direction.BACK_LEFT: "\u2199",
    Direction.BACK_RIGHT: "\u2198",
}
