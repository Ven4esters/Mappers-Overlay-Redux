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

TILTED = Pose(x=100.0, y=200.0, z=50.0, rx=45.0)
#: Пример пользователя: ``Num 9``, шаг 2 м, ``RX = 37°``.
USER_POSE = Pose(x=-1849.342, y=416.528, z=128.826, rx=37.0)


def reference_step(direction: Direction, rx: float, step: float) -> tuple[float, float, float]:
    """Эталон: ``P + Rx(RX)·Δ_local``, ``Δ_local = (±L/√2, 0, ±L/√2)``."""
    ax, ay = direction.axes
    length = math.hypot(ax, ay)
    local_x = -ay / length * step
    local_z = ax / length * step
    angle = math.radians(rx)
    return local_x, -local_z * math.sin(angle), local_z * math.cos(angle)


def test_user_example_at_37_degrees() -> None:
    """Пример пользователя: шаг 2 м, ``RX = 37°`` → ``Y 415.677``, ``Z 129.955``."""
    result = shifted(USER_POSE, Direction.FORWARD_RIGHT, 2.0)
    assert result.y == pytest.approx(415.676, abs=0.002)
    assert result.z == pytest.approx(129.955, abs=0.002)
    # без X шаг был бы короче шага в √2 раза
    assert result.x == pytest.approx(USER_POSE.x + 2.0 / math.sqrt(2.0), abs=0.002)


def test_diagonal_at_zero_is_forward_and_up() -> None:
    """При ``RX = 0`` диагональ идёт по ``X`` и ``Z`` на ``шаг/√2``."""
    result = shifted(BASE, Direction.FORWARD_RIGHT, 5.0)
    component = 5.0 / math.sqrt(2.0)
    assert result.x == pytest.approx(BASE.x + component, abs=0.001)
    assert result.y == pytest.approx(BASE.y, abs=0.001)
    assert result.z == pytest.approx(BASE.z + component, abs=0.001)


@pytest.mark.parametrize("rx", [-60.0, -37.0, -12.5, 0.0, 12.5, 30.0, 37.0, 45.0, 60.0, 80.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_is_the_local_step_rotated_by_rx(direction: Direction, rx: float) -> None:
    """``P_new = P + Rx(RX) · Δ_local``: локальная диагональ, повёрнутая на ``RX``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, direction, 1.0)
    expected = reference_step(direction, rx, 1.0)
    assert result.x == pytest.approx(expected[0], abs=0.002)
    assert result.y == pytest.approx(expected[1], abs=0.002)
    assert result.z == pytest.approx(expected[2], abs=0.002)


@pytest.mark.parametrize("rx", [-37.0, 0.0, 12.5, 37.0, 45.0, 90.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_keeps_its_local_direction_at_any_angle(direction: Direction, rx: float) -> None:
    """Обратный поворот на ``−RX`` возвращает ту же локальную диагональ."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, direction, 1.0)
    dx, dy, dz = result.x - pose.x, result.y - pose.y, result.z - pose.z
    angle = -math.radians(rx)
    back_y = dy * math.cos(angle) - dz * math.sin(angle)
    back_z = dy * math.sin(angle) + dz * math.cos(angle)
    ax, ay = direction.axes
    assert dx == pytest.approx(ay / math.sqrt(2.0) * -1.0, abs=0.002)
    assert back_y == pytest.approx(0.0, abs=0.002)
    assert back_z == pytest.approx(ax / math.sqrt(2.0), abs=0.002)


@pytest.mark.parametrize("rx", [-90.0, -45.0, -37.0, 0.0, 30.0, 37.0, 45.0, 90.0])
def test_diagonal_keeps_neighbours_perpendicular(rx: float) -> None:
    """Поворот не меняет углы: соседние диагонали остаются под 90°."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    steps = {}
    for direction in (Direction.FORWARD_RIGHT, Direction.FORWARD_LEFT, Direction.BACK_RIGHT):
        result = shifted(pose, direction, 1.0)
        steps[direction] = (result.x, result.y - pose.y, result.z - pose.z)
    up_right = steps[Direction.FORWARD_RIGHT]
    for direction in (Direction.FORWARD_LEFT, Direction.BACK_RIGHT):
        other = steps[direction]
        assert sum(a * b for a, b in zip(up_right, other, strict=True)) == pytest.approx(
            0.0, abs=0.004
        )


@pytest.mark.parametrize("rx", [-37.0, 0.0, 37.0, 45.0, 90.0])
def test_opposite_diagonals_cancel_out(rx: float) -> None:
    """Противоположные клавиши дают противоположные шаги по всем осям."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    pairs = (
        (Direction.FORWARD_RIGHT, Direction.BACK_LEFT),
        (Direction.FORWARD_LEFT, Direction.BACK_RIGHT),
        (Direction.FORWARD, Direction.BACK),
    )
    for first, second in pairs:
        one = shifted(pose, first, 1.0)
        two = shifted(pose, second, 1.0)
        for axis in ("x", "y", "z"):
            first_delta = getattr(one, axis) - getattr(pose, axis)
            second_delta = getattr(two, axis) - getattr(pose, axis)
            assert first_delta == pytest.approx(-second_delta, abs=0.002)


@pytest.mark.parametrize("rx", [-60.0, -37.0, 0.0, 20.0, 37.0, 45.0, 80.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_length_is_exactly_one_step(direction: Direction, rx: float) -> None:
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, direction, 2.0)
    distance = math.dist((result.x, result.y, result.z), (pose.x, pose.y, pose.z))
    assert distance == pytest.approx(2.0, abs=0.002)


@pytest.mark.parametrize("step", [0.5, 1.0, 2.0, 5.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_is_one_step_along_the_line(direction: Direction, step: float) -> None:
    result = shifted(BASE, direction, step)
    distance = math.dist((result.x, result.y, result.z), (BASE.x, BASE.y, BASE.z))
    assert distance == pytest.approx(step, abs=0.001)


@pytest.mark.parametrize("rz", [0.0, 45.0, 90.0, 180.0])
def test_diagonal_does_not_depend_on_rotation(rz: float) -> None:
    """Диагонали поворачиваются на ``RX``, но ``RZ`` их не крутит (как и раньше)."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=37.0, rz=rz)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.y == pytest.approx(-0.426, abs=0.002)
    assert result.z == pytest.approx(0.565, abs=0.002)


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
    assert changed_fields(tilted, diagonal) == (Field.X, Field.Y, Field.Z)


def test_changed_fields_ignores_submillimetre_noise() -> None:
    slightly = Pose(x=BASE.x + 0.0004, y=BASE.y, z=BASE.z)
    assert changed_fields(BASE, slightly) == ()


ALT = Pose(x=100.0, y=200.0, z=50.0, rx=0.0, ry=0.0, rz=0.0)
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


def test_alt_keeps_the_diagonals_working() -> None:
    """Диагонали в режиме высоты не меняются: поворот от ``RX`` остаётся."""
    without = shifted(ALT, Direction.FORWARD_RIGHT, 1.0)
    with_alt = shifted(ALT, Direction.FORWARD_RIGHT, 1.0, tilt=True)
    assert with_alt == without
    assert with_alt.x == pytest.approx(100.0 + HALF, abs=0.001)
    assert with_alt.y == ALT.y
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
