"""Сдвиг позы: таблица из README и граничные случаи."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.movement import changed_fields, shifted, validate_step
from map_overlay.domain.pose import Pose
from map_overlay.errors import ValidationError

BASE = Pose(x=1850.0, y=1850.0, z=100.0, rx=0.0, ry=0.0, rz=0.0)

DIAGONAL = 5.0 / math.sqrt(2.0)

EXPECTED = {
    Direction.FORWARD: (1855.0, 1850.0),
    Direction.BACK: (1845.0, 1850.0),
    Direction.LEFT: (1850.0, 1855.0),
    Direction.RIGHT: (1850.0, 1845.0),
}

#: Диагональные клавиши в обычном режиме повторяют направления режима по экрану:
#: ``(ΔY, ΔZ)`` при шаге 5 м.
DIAGONAL_SCREEN = {
    Direction.FORWARD_RIGHT: (1850.0 - DIAGONAL, 100.0 + DIAGONAL),  # Num 9 — вверх-вправо
    Direction.FORWARD_LEFT: (1850.0 + DIAGONAL, 100.0 + DIAGONAL),  # Num 7 — вверх-влево
    Direction.BACK_LEFT: (1850.0 + DIAGONAL, 100.0 - DIAGONAL),  # Num 1 — вниз-влево
    Direction.BACK_RIGHT: (1850.0 - DIAGONAL, 100.0 - DIAGONAL),  # Num 3 — вниз-вправо
}


@pytest.mark.parametrize(("direction", "expected"), EXPECTED.items())
def test_step_matches_user_table(direction: Direction, expected: tuple[float, float]) -> None:
    result = shifted(BASE, direction, 5.0)
    assert result.x == pytest.approx(expected[0], abs=0.001)
    assert result.y == pytest.approx(expected[1], abs=0.001)


@pytest.mark.parametrize(("direction", "expected"), DIAGONAL_SCREEN.items())
def test_diagonal_keys_repeat_the_screen_mode(
    direction: Direction, expected: tuple[float, float]
) -> None:
    """Диагонали в обычном режиме идут по экрану: ``Y`` и ``Z``, ``X`` на месте."""
    result = shifted(BASE, direction, 5.0)
    assert result.x == BASE.x
    assert result.y == pytest.approx(expected[0], abs=0.001)
    assert result.z == pytest.approx(expected[1], abs=0.001)


@pytest.mark.parametrize("direction", [d for d in Direction if not d.is_diagonal])
def test_height_and_angles_never_change(direction: Direction) -> None:
    pose = Pose(x=10.0, y=20.0, z=30.0, rx=1.0, ry=2.0, rz=3.0)
    result = shifted(pose, direction, 1.0)
    assert result.z == 30.0
    assert (result.rx, result.ry, result.rz) == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_keeps_angles(direction: Direction) -> None:
    pose = Pose(x=10.0, y=20.0, z=30.0, rx=1.0, ry=2.0, rz=3.0)
    result = shifted(pose, direction, 1.0)
    assert (result.rx, result.ry, result.rz) == (1.0, 2.0, 3.0)


def test_result_is_rounded_to_millimetres() -> None:
    pose = Pose(x=0.1, y=0.2)
    assert shifted(pose, Direction.FORWARD, 0.1).x == 0.2
    assert shifted(pose, Direction.BACK, 0.1).x == 0.0
    assert shifted(pose, Direction.RIGHT, 0.1).y == 0.1


@pytest.mark.parametrize("step", [0.5, 1.0, 2.0, 5.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_is_one_step_along_the_line(direction: Direction, step: float) -> None:
    result = shifted(BASE, direction, step)
    distance = math.hypot(result.y - BASE.y, result.z - BASE.z)
    assert distance == pytest.approx(step, abs=0.001)
    assert result.x == BASE.x


@pytest.mark.parametrize("rz", [0.0, 45.0, 90.0, 180.0])
def test_diagonal_does_not_depend_on_rotation(rz: float) -> None:
    """Диагонали повторяют экранные направления, поэтому ``RZ`` их не крутит."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rz=rz)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.y == pytest.approx(-0.707, abs=0.001)
    assert result.z == pytest.approx(0.707, abs=0.001)


@pytest.mark.parametrize(
    ("rz", "direction", "expected_dx", "expected_dy"),
    [
        (0.0, Direction.FORWARD, 1.0, 0.0),
        (90.0, Direction.FORWARD, 0.0, 1.0),
        (-90.0, Direction.FORWARD, 0.0, -1.0),
        (180.0, Direction.FORWARD, -1.0, 0.0),
        (0.0, Direction.LEFT, 0.0, 1.0),
        (90.0, Direction.LEFT, -1.0, 0.0),
        (-90.0, Direction.LEFT, 1.0, 0.0),
        (45.0, Direction.BACK, -0.707, -0.707),
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
    result = shifted(pose, Direction.LEFT, 2.5)
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
    assert changed_fields(BASE, diagonal) == (Field.Y, Field.Z)


def test_changed_fields_ignores_submillimetre_noise() -> None:
    slightly = Pose(x=BASE.x + 0.0004, y=BASE.y, z=BASE.z)
    assert changed_fields(BASE, slightly) == ()


SCREEN = Pose(x=100.0, y=200.0, z=50.0, rx=45.0, ry=0.0, rz=0.0)
HALF = math.sqrt(0.5)


def test_screen_forward_goes_up_right() -> None:
    """``Num 8``: ``Y`` в минус, ``Z`` в плюс — на экране вверх-вправо."""
    result = shifted(SCREEN, Direction.FORWARD, 1.0, tilt=True)
    assert result.x == SCREEN.x
    assert result.y == pytest.approx(200.0 - HALF, abs=0.001)
    assert result.z == pytest.approx(50.0 + HALF, abs=0.001)


def test_screen_back_goes_down_left() -> None:
    """``Num 2`` — противоположность ``Num 8``."""
    result = shifted(SCREEN, Direction.BACK, 1.0, tilt=True)
    assert result.y == pytest.approx(200.0 + HALF, abs=0.001)
    assert result.z == pytest.approx(50.0 - HALF, abs=0.001)


def test_screen_left_goes_up_left() -> None:
    """``Num 4`` остаётся как был: ``Y`` в плюс, ``Z`` в плюс."""
    result = shifted(SCREEN, Direction.LEFT, 1.0, tilt=True)
    assert result.y == pytest.approx(200.0 + HALF, abs=0.001)
    assert result.z == pytest.approx(50.0 + HALF, abs=0.001)


def test_screen_right_goes_down_right() -> None:
    result = shifted(SCREEN, Direction.RIGHT, 1.0, tilt=True)
    assert result.y == pytest.approx(200.0 - HALF, abs=0.001)
    assert result.z == pytest.approx(50.0 - HALF, abs=0.001)


@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_screen_diagonals_are_refused(direction: Direction) -> None:
    """В режиме по экрану диагонали не двигают: их просто нет."""
    with pytest.raises(ValidationError):
        shifted(SCREEN, direction, 1.0, tilt=True)


@pytest.mark.parametrize("direction", [d for d in Direction if not d.is_diagonal])
def test_screen_step_keeps_its_length(direction: Direction) -> None:
    result = shifted(SCREEN, direction, 1.0, tilt=True)
    distance = math.dist((SCREEN.y, SCREEN.z), (result.y, result.z))
    assert distance == pytest.approx(1.0, abs=0.002)


@pytest.mark.parametrize("direction", [d for d in Direction if not d.is_diagonal])
def test_screen_step_never_touches_x(direction: Direction) -> None:
    """В глубину шаг не уходит: ``X`` остаётся на месте."""
    assert shifted(SCREEN, direction, 1.0, tilt=True).x == SCREEN.x


def test_screen_mode_ignores_the_angles() -> None:
    """Экранные оси задаёт камера, а не поворот предмета."""
    expected = shifted(SCREEN, Direction.FORWARD, 1.0, tilt=True)
    for angles in ((0.0, 0.0, 0.0), (30.0, 20.0, 10.0), (-60.0, 45.0, 90.0)):
        pose = replace(SCREEN, rx=angles[0], ry=angles[1], rz=angles[2])
        result = shifted(pose, Direction.FORWARD, 1.0, tilt=True)
        assert (result.y - pose.y, result.z - pose.z) == pytest.approx(
            (expected.y - SCREEN.y, expected.z - SCREEN.z), abs=0.001
        )


def test_tilt_is_rounded_to_millimetres() -> None:
    result = shifted(SCREEN, Direction.LEFT, 0.333, tilt=True)
    assert result.y == 200.235
    assert result.z == 50.235


def test_changed_fields_sees_height_on_tilt() -> None:
    assert changed_fields(SCREEN, shifted(SCREEN, Direction.LEFT, 0.5, tilt=True)) == (
        Field.Y,
        Field.Z,
    )
