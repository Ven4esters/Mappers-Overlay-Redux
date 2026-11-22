"""Сдвиг позы: таблица из README и граничные случаи."""

from __future__ import annotations

import math

import pytest
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.movement import changed_fields, shifted, validate_step
from map_overlay.domain.pose import Pose
from map_overlay.errors import ValidationError

BASE = Pose(x=1850.0, y=1850.0, z=100.0, rx=0.0, ry=0.0, rz=0.0)

EXPECTED = {
    Direction.FORWARD: (1845.0, 1850.0),
    Direction.BACK: (1855.0, 1850.0),
    Direction.LEFT: (1850.0, 1845.0),
    Direction.RIGHT: (1850.0, 1855.0),
    Direction.FORWARD_LEFT: (1845.0, 1845.0),
    Direction.FORWARD_RIGHT: (1845.0, 1855.0),
    Direction.BACK_LEFT: (1855.0, 1845.0),
    Direction.BACK_RIGHT: (1855.0, 1855.0),
}


@pytest.mark.parametrize(("direction", "expected"), EXPECTED.items())
def test_step_matches_user_table(direction: Direction, expected: tuple[float, float]) -> None:
    result = shifted(BASE, direction, 5.0)
    assert (result.x, result.y) == expected


@pytest.mark.parametrize("direction", list(Direction))
def test_height_and_angles_never_change(direction: Direction) -> None:
    pose = Pose(x=10.0, y=20.0, z=30.0, rx=1.0, ry=2.0, rz=3.0)
    result = shifted(pose, direction, 1.0)
    assert result.z == 30.0
    assert (result.rx, result.ry, result.rz) == (1.0, 2.0, 3.0)


def test_result_is_rounded_to_millimetres() -> None:
    pose = Pose(x=0.1, y=0.2)
    assert shifted(pose, Direction.FORWARD, 0.1).x == 0.0
    assert shifted(pose, Direction.BACK, 0.1).x == 0.2
    assert shifted(pose, Direction.RIGHT, 0.1).y == 0.3


def test_diagonal_uses_full_step_on_each_axis() -> None:
    result = shifted(BASE, Direction.FORWARD_RIGHT, 2.0)
    assert result.x == 1848.0
    assert result.y == 1852.0


@pytest.mark.parametrize("step", [0.0, -0.5, 0.001, 100.1, math.inf, math.nan])
def test_invalid_step_is_rejected(step: float) -> None:
    with pytest.raises(ValidationError):
        validate_step(step)


def test_step_is_normalised_to_three_decimals() -> None:
    assert validate_step(0.12345) == 0.123
    assert validate_step(0.5) == 0.5


def test_changed_fields_lists_only_real_differences() -> None:
    forward = shifted(BASE, Direction.FORWARD, 0.5)
    assert changed_fields(BASE, forward) == (Field.X,)
    diagonal = shifted(BASE, Direction.FORWARD_LEFT, 0.5)
    assert changed_fields(BASE, diagonal) == (Field.X, Field.Y)


def test_changed_fields_ignores_submillimetre_noise() -> None:
    slightly = Pose(x=BASE.x + 0.0004, y=BASE.y, z=BASE.z)
    assert changed_fields(BASE, slightly) == ()
