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
TILTED = Pose(x=100.0, y=200.0, z=50.0, rx=45.0)
COS37, SIN37 = math.cos(math.radians(37.0)), math.sin(math.radians(37.0))

DIAGONAL_45 = {
    Direction.FORWARD_RIGHT: (TILTED.y - DIAGONAL, TILTED.z + DIAGONAL),
    Direction.FORWARD_LEFT: (TILTED.y + DIAGONAL, TILTED.z + DIAGONAL),
    Direction.BACK_LEFT: (TILTED.y + DIAGONAL, TILTED.z - DIAGONAL),
    Direction.BACK_RIGHT: (TILTED.y - DIAGONAL, TILTED.z - DIAGONAL),
}


@pytest.mark.parametrize(("direction", "expected"), DIAGONAL_45.items())
def test_diagonal_at_45_is_unchanged(direction: Direction, expected: tuple[float, float]) -> None:
    """При ``RX = 45°`` диагонали дают привычные равные компоненты."""
    result = shifted(TILTED, direction, 5.0, tilt=False)
    assert result.x == TILTED.x
    assert result.y == pytest.approx(expected[0], abs=0.001)
    assert result.z == pytest.approx(expected[1], abs=0.001)


def test_diagonal_at_37_follows_the_plane() -> None:
    """При ``RX = 37°`` компоненты берутся из угла: ``cos 37`` и ``sin 37``."""
    pose = replace(TILTED, rx=37.0)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.y == pytest.approx(pose.y - COS37, abs=0.001)
    assert result.z == pytest.approx(pose.z + SIN37, abs=0.001)


def test_diagonal_at_37_is_the_other_key_mirrored() -> None:
    """``Num 7`` — зеркало ``Num 9`` по ``Y``, ``Num 3`` — по ``Z``."""
    pose = replace(TILTED, rx=37.0)
    up_right = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    up_left = shifted(pose, Direction.FORWARD_LEFT, 1.0)
    down_right = shifted(pose, Direction.BACK_RIGHT, 1.0)
    assert up_left.y == pytest.approx(pose.y + COS37, abs=0.001)
    assert up_left.z == pytest.approx(up_right.z, abs=0.001)
    assert down_right.z == pytest.approx(pose.z - SIN37, abs=0.001)
    assert down_right.y == pytest.approx(up_right.y, abs=0.001)


@pytest.mark.parametrize("rx", [-60.0, -37.0, -12.5, 0.0, 12.5, 30.0, 37.0, 45.0, 60.0, 80.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_slope_matches_the_tilt(direction: Direction, rx: float) -> None:
    """Наклон шага на экране равен наклону предмета ``tan RX``: линия к линии."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, direction, 1.0)
    right = -(result.y - pose.y)  # вправо на экране — это ``−Y``
    up = result.z - pose.z
    # координаты пишутся с точностью до миллиметра, отсюда допуск
    assert abs(up / right) == pytest.approx(abs(math.tan(math.radians(rx))), rel=1e-2, abs=5e-3)


def test_negative_tilt_turns_the_diagonal_with_the_surface() -> None:
    """При ``RX < 0`` «вверх-вправо» уходит вниз: клавиша идёт по поверхности.

    Наклон предмета задаёт линию, а не экран: если поверхность опускается вправо,
    то и шаг опускается — иначе он отрывается от плоскости и появляется искажение.
    """
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=-37.0)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.y == pytest.approx(-COS37, abs=0.001)
    assert result.z == pytest.approx(-SIN37, abs=0.001)


@pytest.mark.parametrize("rx", [-60.0, -37.0, 0.0, 20.0, 37.0, 45.0, 80.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_length_is_exactly_one_step(direction: Direction, rx: float) -> None:
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, direction, 2.0)
    assert math.dist((result.y, result.z), (pose.y, pose.z)) == pytest.approx(2.0, abs=0.002)


def test_diagonal_on_a_flat_object_is_horizontal() -> None:
    """У плоского предмета вертикальной составляющей нет: диагональ ложится в ``Y``."""
    flat = Pose(x=0.0, y=0.0, z=0.0, rx=0.0)
    result = shifted(flat, Direction.FORWARD_RIGHT, 1.0)
    assert result.y == pytest.approx(-1.0, abs=0.001)
    assert result.z == 0.0


@pytest.mark.parametrize("step", [0.5, 1.0, 2.0, 5.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_is_one_step_along_the_line(direction: Direction, step: float) -> None:
    result = shifted(BASE, direction, step)
    distance = math.hypot(result.y - BASE.y, result.z - BASE.z)
    assert distance == pytest.approx(step, abs=0.001)
    assert result.x == BASE.x


@pytest.mark.parametrize("rz", [0.0, 45.0, 90.0, 180.0])
def test_diagonal_does_not_depend_on_rotation(rz: float) -> None:
    """Диагонали идут по наклону предмета, но ``RZ`` их не крутит (как и раньше)."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=37.0, rz=rz)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.y == pytest.approx(-COS37, abs=0.001)
    assert result.z == pytest.approx(SIN37, abs=0.001)


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
    tilted = Pose(x=0.0, y=0.0, z=0.0, rx=37.0)
    diagonal = shifted(tilted, Direction.FORWARD_LEFT, 0.5)
    assert changed_fields(tilted, diagonal) == (Field.Y, Field.Z)


def test_changed_fields_ignores_submillimetre_noise() -> None:
    slightly = Pose(x=BASE.x + 0.0004, y=BASE.y, z=BASE.z)
    assert changed_fields(BASE, slightly) == ()


ALT = Pose(x=100.0, y=200.0, z=50.0, rx=45.0, ry=0.0, rz=0.0)
HALF = math.sqrt(0.5)


def test_alt_forward_goes_up() -> None:
    """``Num 8`` с ``Alt``: ``Z`` в плюс на весь шаг, ``X`` и ``Y`` на месте."""
    result = shifted(ALT, Direction.FORWARD, 1.0, tilt=True)
    assert (result.x, result.y) == (ALT.x, ALT.y)
    assert result.z == pytest.approx(51.0, abs=0.001)


def test_alt_back_goes_down() -> None:
    result = shifted(ALT, Direction.BACK, 1.0, tilt=True)
    assert (result.x, result.y) == (ALT.x, ALT.y)
    assert result.z == pytest.approx(49.0, abs=0.001)


def test_alt_left_and_right_stay_horizontal() -> None:
    """``Num 4/6`` в режиме высоты работают как обычно — по ``Y``, с поворотом ``RZ``."""
    left = shifted(ALT, Direction.LEFT, 1.0, tilt=True)
    assert left.y == pytest.approx(201.0, abs=0.001)
    assert left.z == ALT.z
    right = shifted(ALT, Direction.RIGHT, 1.0, tilt=True)
    assert right.y == pytest.approx(199.0, abs=0.001)
    assert right.z == ALT.z


def test_alt_keeps_the_diagonals_on_screen() -> None:
    """Диагонали в режиме высоты не меняются: они и так идут по экрану."""
    without = shifted(ALT, Direction.FORWARD_RIGHT, 1.0)
    with_alt = shifted(ALT, Direction.FORWARD_RIGHT, 1.0, tilt=True)
    assert with_alt == without
    assert with_alt.y == pytest.approx(200.0 - HALF, abs=0.001)
    assert with_alt.z == pytest.approx(50.0 + HALF, abs=0.001)


@pytest.mark.parametrize("angles", [(0.0, 0.0, 0.0), (30.0, 20.0, 10.0), (-60.0, 45.0, 90.0)])
def test_alt_height_does_not_depend_on_the_angles(angles: tuple[float, float, float]) -> None:
    pose = replace(ALT, rx=angles[0], ry=angles[1], rz=angles[2])
    result = shifted(pose, Direction.FORWARD, 1.0, tilt=True)
    assert result.z == pytest.approx(pose.z + 1.0, abs=0.001)
    assert (result.x, result.y) == (pose.x, pose.y)


@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.BACK])
def test_alt_never_touches_the_ground_axes(direction: Direction) -> None:
    result = shifted(ALT, direction, 2.5, tilt=True)
    assert (result.x, result.y) == (ALT.x, ALT.y)
    assert abs(result.z - ALT.z) == pytest.approx(2.5, abs=0.001)


def test_tilt_is_rounded_to_millimetres() -> None:
    result = shifted(ALT, Direction.FORWARD, 0.333, tilt=True)
    assert result.z == 50.333


def test_changed_fields_sees_height_on_tilt() -> None:
    assert changed_fields(ALT, shifted(ALT, Direction.FORWARD, 0.5, tilt=True)) == (Field.Z,)
