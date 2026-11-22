"""Направления движения пропа в локальных осях предмета.

Восемь направлений в плоскости ``XY`` плюс ``UP``/``DOWN`` по ``Z``.
Диагоналей в пространстве ``Z`` нет — это осознанное ограничение (см. ADR-0002).
"""

from __future__ import annotations

from enum import StrEnum

from lsp_overlay.domain.geometry import Vec3


class Direction(StrEnum):
    """Направление сдвига относительно предмета."""

    NORTH = "north"
    NORTH_EAST = "north_east"
    EAST = "east"
    SOUTH_EAST = "south_east"
    SOUTH = "south"
    SOUTH_WEST = "south_west"
    WEST = "west"
    NORTH_WEST = "north_west"
    UP = "up"
    DOWN = "down"


class DiagonalMode(StrEnum):
    """Как считать диагональный шаг.

    * ``SAME_DISTANCE`` — диагональ длиной ровно ``step`` (компоненты делятся на √2);
    * ``SAME_STEP`` — по ``step`` на каждую ось (диагональ длиннее в √2 раза).
    """

    SAME_DISTANCE = "same_distance"
    SAME_STEP = "same_step"


LOCAL_VECTORS: dict[Direction, Vec3] = {
    Direction.NORTH: (0.0, 1.0, 0.0),
    Direction.NORTH_EAST: (1.0, 1.0, 0.0),
    Direction.EAST: (1.0, 0.0, 0.0),
    Direction.SOUTH_EAST: (1.0, -1.0, 0.0),
    Direction.SOUTH: (0.0, -1.0, 0.0),
    Direction.SOUTH_WEST: (-1.0, -1.0, 0.0),
    Direction.WEST: (-1.0, 0.0, 0.0),
    Direction.NORTH_WEST: (-1.0, 1.0, 0.0),
    Direction.UP: (0.0, 0.0, 1.0),
    Direction.DOWN: (0.0, 0.0, -1.0),
}

PLANAR_DIRECTIONS: tuple[Direction, ...] = (
    Direction.NORTH_WEST,
    Direction.NORTH,
    Direction.NORTH_EAST,
    Direction.WEST,
    Direction.EAST,
    Direction.SOUTH_WEST,
    Direction.SOUTH,
    Direction.SOUTH_EAST,
)

VERTICAL_DIRECTIONS: tuple[Direction, ...] = (Direction.UP, Direction.DOWN)


def local_vector(direction: Direction) -> Vec3:
    """Единичный (для диагоналей — нормируемый позже) вектор в локальных осях."""
    return LOCAL_VECTORS[direction]


def is_diagonal(direction: Direction) -> bool:
    """Диагональ ли это в плоскости ``XY``."""
    vector = LOCAL_VECTORS[direction]
    return vector[0] != 0.0 and vector[1] != 0.0
