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

DIAGONAL = 5.0 / math.sqrt(2.0)

EXPECTED = {
    Direction.FORWARD: (1845.0, 1850.0),
    Direction.BACK: (1855.0, 1850.0),
    Direction.LEFT: (1850.0, 1845.0),
    Direction.RIGHT: (1850.0, 1855.0),
    Direction.FORWARD_LEFT: (1850.0 - DIAGONAL, 1850.0 - DIAGONAL),
    Direction.FORWARD_RIGHT: (1850.0 - DIAGONAL, 1850.0 + DIAGONAL),
    Direction.BACK_LEFT: (1850.0 + DIAGONAL, 1850.0 - DIAGONAL),
    Direction.BACK_RIGHT: (1850.0 + DIAGONAL, 1850.0 + DIAGONAL),
}


@pytest.mark.parametrize(("direction", "expected"), EXPECTED.items())
def test_step_matches_user_table(direction: Direction, expected: tuple[float, float]) -> None:
    result = shifted(BASE, direction, 5.0)
    assert result.x == pytest.approx(expected[0], abs=0.001)
    assert result.y == pytest.approx(expected[1], abs=0.001)


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


@pytest.mark.parametrize("step", [0.5, 1.0, 2.0, 5.0])
@pytest.mark.parametrize("direction", [Direction.FORWARD_LEFT, Direction.BACK_RIGHT])
def test_diagonal_is_one_step_along_the_line(direction: Direction, step: float) -> None:
    result = shifted(BASE, direction, step)
    distance = math.hypot(result.x - BASE.x, result.y - BASE.y)
    assert distance == pytest.approx(step, abs=0.001)


@pytest.mark.parametrize(
    ("rz", "direction", "expected_dx", "expected_dy"),
    [
        (0.0, Direction.FORWARD, -1.0, 0.0),
        (90.0, Direction.FORWARD, 0.0, -1.0),
        (-90.0, Direction.FORWARD, 0.0, 1.0),
        (180.0, Direction.FORWARD, 1.0, 0.0),
        (0.0, Direction.LEFT, 0.0, -1.0),
        (90.0, Direction.LEFT, 1.0, 0.0),
        (-90.0, Direction.LEFT, -1.0, 0.0),
        (45.0, Direction.BACK_RIGHT, 0.0, 1.0),
    ],
)
def test_rotation_turns_the_direction(
    rz: float, direction: Direction, expected_dx: float, expected_dy: float
) -> None:
    pose = Pose(x=100.0, y=200.0, rz=rz)
    result = shifted(pose, direction, 1.0)
    assert result.x - pose.x == pytest.approx(expected_dx, abs=0.001)
    assert result.y - pose.y == pytest.approx(expected_dy, abs=0.001)


@pytest.mark.parametrize("rz", [-120.0, -45.0, 0.0, 30.0, 90.0, 175.0])
def test_step_length_does_not_depend_on_rotation(rz: float) -> None:
    pose = Pose(x=0.0, y=0.0, rz=rz)
    result = shifted(pose, Direction.BACK_LEFT, 2.5)
    assert math.hypot(result.x, result.y) == pytest.approx(2.5, abs=0.001)


def test_rotation_does_not_change_height_or_angles() -> None:
    pose = Pose(x=10.0, y=20.0, z=30.0, rx=5.0, ry=7.0, rz=33.0)
    result = shifted(pose, Direction.RIGHT, 1.0)
    assert (result.z, result.rx, result.ry, result.rz) == (30.0, 5.0, 7.0, 33.0)


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
