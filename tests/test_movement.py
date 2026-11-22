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

DIAGONAL = 5.0  # диагональ идёт на полный шаг

EXPECTED = {
    Direction.FORWARD: (1855.0, 1850.0),
    Direction.BACK: (1845.0, 1850.0),
    Direction.LEFT: (1850.0, 1855.0),
    Direction.RIGHT: (1850.0, 1845.0),
}

TILTED = Pose(x=100.0, y=200.0, z=50.0, rx=45.0)
#: Пример пользователя: ``Num 9``, шаг 2 м, ``RX = 37°``.
USER_POSE = Pose(x=-1849.342, y=416.528, z=128.826, rx=37.0)


def reference_step(
    direction: Direction, rx: float, ry: float, step: float
) -> tuple[float, float, float]:
    """Эталон по случаям: без наклона — горизонталь, только `RX` — плоскость `Y/Z`."""
    ax, ay = direction.axes
    arm = step / math.hypot(ax, ay)
    if rx == 0.0:
        return ax * arm, ay * arm, 0.0
    if ry == 0.0:
        angle = math.radians(rx)
        return 0.0, ay * arm * math.sin(angle), ax * arm * math.cos(angle)
    return reference_step_2d(direction, rx, ry, step)


#: Задание 1.6.2: ``Num 9``, шаг 3 м, ``RX = 55°``, ``RY = 17°``.
RY_POSE = Pose(x=-1849.342, y=416.528, z=128.826, rx=55.0, ry=17.0)


def reference_step_2d(
    direction: Direction, rx: float, ry: float, step: float
) -> tuple[float, float, float]:
    """Формула задания: ``ΔX = ax·L·sin RY``, ``ΔY = ay·L·sin RX·cos RY``,
    ``ΔZ = ax·L·cos RX·cos RY`` при ``L = шаг``."""
    ax, ay = direction.axes
    arm = step
    tx, ty = math.radians(rx), math.radians(ry)
    return (
        ax * arm * math.sin(ty),
        ay * arm * math.sin(tx) * math.cos(ty),
        ax * arm * math.cos(tx) * math.cos(ty),
    )


def test_user_example_with_rx_and_ry() -> None:
    """Задание: ``RX = 55°``, ``RY = 17°``, шаг 3 м, «вверх-вправо» → панель до миллиметра."""
    result = shifted(RY_POSE, Direction.FORWARD_RIGHT, 3.0)
    assert (result.x, result.y, result.z) == (-1848.465, 414.178, 130.472)


#: Второй эталон заказчика (подтверждён в игре): ``Num 9``, шаг 3 м, ``RX = 41.5°``, ``RY = 22.3°``.
SECOND_POSE = Pose(x=-1849.342, y=416.528, z=128.816, rx=41.5, ry=22.3)


def test_second_user_example_with_rx_and_ry() -> None:
    """``RX = 41.5°``, ``RY = 22.3°``, шаг 3 м, «вверх-вправо»."""
    result = shifted(SECOND_POSE, Direction.FORWARD_RIGHT, 3.0)
    assert (result.x, result.y, result.z) == (-1848.204, 414.689, 130.895)


def test_second_user_example_keeps_the_step_length() -> None:
    """Длина того же шага ровно 3 м: ``Δ = (+1.138, −1.839, +2.079)``."""
    result = shifted(SECOND_POSE, Direction.FORWARD_RIGHT, 3.0)
    distance = math.dist(
        (result.x, result.y, result.z), (SECOND_POSE.x, SECOND_POSE.y, SECOND_POSE.z)
    )
    assert distance == pytest.approx(3.0, abs=0.002)


def test_user_example_with_rx_and_ry_in_metres() -> None:
    """Тот же пример в метрах: ``ΔX = +0.8771``, ``ΔY = −2.3501``, ``ΔZ = +1.6455``."""
    result = shifted(RY_POSE, Direction.FORWARD_RIGHT, 3.0)
    assert result.x - RY_POSE.x == pytest.approx(0.8771, abs=0.001)
    assert result.y - RY_POSE.y == pytest.approx(-2.3501, abs=0.001)
    assert result.z - RY_POSE.z == pytest.approx(1.6455, abs=0.001)


def test_user_example_at_37_degrees() -> None:
    """Шаг 2 м, ``RX = 37°``, ``RY = 0``: ``X`` тот же, ``Y 415.677``, ``Z 129.955``.

    Это случай «наклонён только ``RX``» — формула 1.5.4 действует как раньше.
    """
    result = shifted(USER_POSE, Direction.FORWARD_RIGHT, 2.0)
    assert result.x == USER_POSE.x
    assert result.y == pytest.approx(415.677, abs=0.002)
    assert result.z == pytest.approx(129.955, abs=0.002)


@pytest.mark.parametrize("rx", [-60.0, -37.0, -12.5, 12.5, 30.0, 37.0, 45.0, 60.0, 80.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_is_the_rotated_plane_step(direction: Direction, rx: float) -> None:
    """Случай «только ``RX``»: ``ΔY = ay·(шаг/√2)·sin RX``, ``ΔZ = ax·(шаг/√2)·cos RX``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, direction, 1.0)
    expected = reference_step(direction, rx, 0.0, 1.0)
    assert result.x == pose.x
    assert result.y == pytest.approx(expected[1], abs=0.002)
    assert result.z == pytest.approx(expected[2], abs=0.002)


@pytest.mark.parametrize("rz", [0.0, 45.0, 90.0, -90.0, 180.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_without_tilt_is_horizontal(direction: Direction, rz: float) -> None:
    """Случай «наклона нет»: диагональ идёт в горизонтали, ``Z`` не меняется, длина — шаг."""
    pose = Pose(x=10.0, y=-20.0, z=5.0, rz=rz)
    result = shifted(pose, direction, 2.0)
    assert result.z == pose.z
    ax, ay = direction.axes
    arm = 2.0 / math.hypot(ax, ay)
    angle = math.radians(rz)
    expected_dx = ax * arm * math.cos(angle) - ay * arm * math.sin(angle)
    expected_dy = ax * arm * math.sin(angle) + ay * arm * math.cos(angle)
    assert result.x - pose.x == pytest.approx(expected_dx, abs=0.002)
    assert result.y - pose.y == pytest.approx(expected_dy, abs=0.002)
    distance = math.dist((result.x, result.y), (pose.x, pose.y))
    assert distance == pytest.approx(2.0, abs=0.002)


def test_diagonal_without_tilt_goes_forward_right() -> None:
    """``Num 9`` без наклона — вперёд и вправо: ``ΔX > 0``, ``ΔY < 0``, ``ΔZ = 0``."""
    pose = Pose(x=0.0, y=0.0, z=0.0)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.x == pytest.approx(1.0 / math.sqrt(2.0), abs=0.002)
    assert result.y == pytest.approx(-1.0 / math.sqrt(2.0), abs=0.002)
    assert result.z == 0.0


def test_diagonal_without_tilt_rotates_with_rz() -> None:
    """Без наклона ``RZ = 90°`` поворачивает диагональ вместе с прямыми клавишами."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rz=90.0)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.x == pytest.approx(1.0 / math.sqrt(2.0), abs=0.002)
    assert result.y == pytest.approx(1.0 / math.sqrt(2.0), abs=0.002)
    assert result.z == 0.0


@pytest.mark.parametrize("ry", [-90.0, -45.0, -17.0, 0.0, 17.0, 37.0, 90.0])
@pytest.mark.parametrize("rx", [-45.0, -12.5, 0.0, 12.5, 37.0, 55.0, 80.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_follows_rx_and_ry(direction: Direction, rx: float, ry: float) -> None:
    """Все три случая по углам: совпадение с эталонной формулой до миллиметра."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx, ry=ry)
    result = shifted(pose, direction, 1.0)
    expected = reference_step(direction, rx, ry, 1.0)
    assert result.x == pytest.approx(expected[0], abs=0.002)
    assert result.y == pytest.approx(expected[1], abs=0.002)
    assert result.z == pytest.approx(expected[2], abs=0.002)


@pytest.mark.parametrize("ry", [-90.0, -37.0, 17.0, 45.0, 90.0])
@pytest.mark.parametrize("rx", [-55.0, 12.5, 37.0, 55.0, 90.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_length_is_the_full_step_with_both_angles(
    direction: Direction, rx: float, ry: float
) -> None:
    """Два поворота вектор не растягивают: длина всегда равна шагу."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx, ry=ry)
    result = shifted(pose, direction, 2.0)
    distance = math.dist((result.x, result.y, result.z), (pose.x, pose.y, pose.z))
    assert distance == pytest.approx(2.0, abs=0.003)


@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_at_zero_ry_keeps_the_old_formula(direction: Direction) -> None:
    """При ``RY = 0`` глубина не меняется, а ``Y``/``Z`` считаются по ``RX``."""
    pose = Pose(x=5.0, y=-3.0, z=7.0, rx=37.0, ry=0.0)
    result = shifted(pose, direction, 3.0)
    ax, ay = direction.axes
    arm = 3.0 / math.hypot(ax, ay)
    assert result.x == pose.x
    assert result.y - pose.y == pytest.approx(ay * arm * math.sin(math.radians(37.0)), abs=0.002)
    assert result.z - pose.z == pytest.approx(ax * arm * math.cos(math.radians(37.0)), abs=0.002)


@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_depth_follows_the_sign_of_ry(direction: Direction) -> None:
    """``RY`` в плюс уводит вперёд, в минус — назад; ``Y`` и ``Z`` от знака ``RY`` не зависят."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=37.0)
    forward = shifted(replace(pose, ry=17.0), direction, 1.0)
    backward = shifted(replace(pose, ry=-17.0), direction, 1.0)
    assert forward.x == pytest.approx(-backward.x, abs=0.002)
    assert forward.y == pytest.approx(backward.y, abs=0.002)
    assert forward.z == pytest.approx(backward.z, abs=0.002)


def test_up_diagonal_goes_into_plus_x_and_down_diagonal_into_minus_x() -> None:
    """«Вверх-*» уходят вперёд, «вниз-*» — назад."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=37.0, ry=17.0)
    assert shifted(pose, Direction.FORWARD_RIGHT, 1.0).x > 0
    assert shifted(pose, Direction.FORWARD_LEFT, 1.0).x > 0
    assert shifted(pose, Direction.BACK_RIGHT, 1.0).x < 0
    assert shifted(pose, Direction.BACK_LEFT, 1.0).x < 0


@pytest.mark.parametrize("ry", [2.5, 17.0, 37.0, 60.0, 89.0])
def test_diagonal_components_shrink_with_ry(ry: float) -> None:
    """При ``RX ≠ 0``: ``Y``/``Z`` сжимаются множителем ``cos RY``, ``X`` растёт как ``sin RY``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=55.0, ry=ry)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.z == pytest.approx(
        math.cos(math.radians(55.0)) * math.cos(math.radians(ry)), abs=0.002
    )
    assert result.x == pytest.approx(math.sin(math.radians(ry)), abs=0.002)


@pytest.mark.parametrize("rx", [12.5, 30.0, 37.0, 45.0, 60.0, 80.0])
def test_diagonal_tilt_on_screen_is_ninety_minus_rx(rx: float) -> None:
    """Наклон диагонали на экране равен ``90° − RX``: 45° при 45°, круче к нулю."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    right = -(result.y - pose.y)  # вправо на экране — это ``−Y``
    up = result.z - pose.z
    assert up / right == pytest.approx(
        math.cos(math.radians(rx)) / math.sin(math.radians(rx)), rel=1e-2, abs=5e-3
    )


@pytest.mark.parametrize("rx", [-37.0, 12.5, 37.0, 45.0, 90.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_moves_nothing_along_x(direction: Direction, rx: float) -> None:
    """При ``RX ≠ 0`` и ``RY = 0`` глубина ``X`` диагоналями не меняется."""
    pose = Pose(x=12.5, y=-3.0, z=7.0, rx=rx)
    assert shifted(pose, direction, 3.0).x == pose.x


@pytest.mark.parametrize("ry", [-17.0, 0.0, 17.0, 37.0])
@pytest.mark.parametrize("rx", [-37.0, 0.0, 37.0, 45.0, 90.0])
def test_opposite_diagonals_cancel_out(rx: float, ry: float) -> None:
    """Противоположные клавиши дают противоположные шаги по ``X``, ``Y`` и ``Z``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx, ry=ry)
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


@pytest.mark.parametrize("rx", [-37.0, 0.0, 20.0, 37.0, 45.0, 80.0])
def test_diagonal_keys_are_mirror_symmetric(rx: float) -> None:
    """``Num 7`` — зеркало ``Num 9`` по ``Y``, ``Num 3`` — по ``Z``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    up_right = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    up_left = shifted(pose, Direction.FORWARD_LEFT, 1.0)
    down_right = shifted(pose, Direction.BACK_RIGHT, 1.0)
    assert up_left.y - pose.y == pytest.approx(-(up_right.y - pose.y), abs=0.002)
    assert up_left.z - pose.z == pytest.approx(up_right.z - pose.z, abs=0.002)
    assert down_right.z - pose.z == pytest.approx(-(up_right.z - pose.z), abs=0.002)
    assert down_right.y - pose.y == pytest.approx(up_right.y - pose.y, abs=0.002)


@pytest.mark.parametrize("rx", [-60.0, -37.0, 20.0, 37.0, 45.0, 80.0])
@pytest.mark.parametrize("direction", [d for d in Direction if d.is_diagonal])
def test_diagonal_length_in_the_yz_plane(direction: Direction, rx: float) -> None:
    """Случай «только ``RX``»: длина шага в плоскости ``Y/Z`` равна ``шаг/√2``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx)
    result = shifted(pose, direction, 2.0)
    distance = math.dist((result.y, result.z), (pose.y, pose.z))
    assert distance == pytest.approx(2.0 / math.sqrt(2.0), abs=0.002)


@pytest.mark.parametrize("rz", [0.0, 45.0, 90.0, 180.0])
def test_diagonal_does_not_depend_on_rotation(rz: float) -> None:
    """Диагонали поворачиваются на ``RX``, но ``RZ`` их не крутит (как и раньше)."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=37.0, rz=rz)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.y == pytest.approx(-0.426, abs=0.002)
    assert result.z == pytest.approx(0.565, abs=0.002)


@pytest.mark.parametrize("rz", [0.0, 45.0, 90.0, 180.0])
def test_diagonal_with_two_angles_does_not_depend_on_rotation(rz: float) -> None:
    """Случай «``RX`` и ``RY``» тоже не зависит от ``RZ``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=55.0, ry=17.0, rz=rz)
    result = shifted(pose, Direction.FORWARD_RIGHT, 1.0)
    assert result.x == pytest.approx(0.292, abs=0.002)
    assert result.y == pytest.approx(-0.783, abs=0.002)
    assert result.z == pytest.approx(0.549, abs=0.002)


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


ALT = Pose(x=100.0, y=200.0, z=50.0, rx=37.0, ry=0.0, rz=0.0)
HALF = math.sqrt(0.5)
COS37, SIN37 = math.cos(math.radians(37.0)), math.sin(math.radians(37.0))


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
    assert with_alt.x == ALT.x
    assert with_alt.y == pytest.approx(200.0 - HALF * SIN37, abs=0.001)
    assert with_alt.z == pytest.approx(50.0 + HALF * COS37, abs=0.001)


def test_alt_step_follows_ry() -> None:
    """Эталон заказчика: ``RY = 10°``, шаг 3.0 → ``(0.520944533, 0, 2.954423259)``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, ry=10.0)
    result = shifted(pose, Direction.FORWARD, 3.0, tilt=True)
    assert result.x == pytest.approx(0.520944533, abs=0.001)
    assert result.y == 0.0
    assert result.z == pytest.approx(2.954423259, abs=0.001)


@pytest.mark.parametrize("ry", [-60.0, -37.0, -10.0, 0.0, 10.0, 37.0, 60.0, 90.0])
def test_alt_step_keeps_the_step_length(ry: float) -> None:
    """Поворот вокруг ``Y`` сохраняет длину: ``sin² + cos² = 1``."""
    pose = Pose(x=0.0, y=0.0, z=0.0, ry=ry)
    result = shifted(pose, Direction.FORWARD, 2.0, tilt=True)
    assert math.hypot(result.x, result.z) == pytest.approx(2.0, abs=0.002)


@pytest.mark.parametrize("ry", [-45.0, 0.0, 10.0, 37.0, 60.0])
def test_alt_forward_and_back_are_opposite(ry: float) -> None:
    pose = Pose(x=0.0, y=0.0, z=0.0, ry=ry)
    up = shifted(pose, Direction.FORWARD, 2.0, tilt=True)
    down = shifted(pose, Direction.BACK, 2.0, tilt=True)
    assert up.x == pytest.approx(-down.x, abs=0.002)
    assert up.z == pytest.approx(-down.z, abs=0.002)


@pytest.mark.parametrize("angles", [(0.0, 0.0, 0.0), (30.0, 0.0, 10.0), (-60.0, 0.0, 90.0)])
def test_alt_height_does_not_depend_on_rx_and_rz(angles: tuple[float, float, float]) -> None:
    """``RX`` и ``RZ`` на высоту не влияют: ось ``Z`` задаёт только ``RY``."""
    pose = replace(ALT, rx=angles[0], ry=angles[1], rz=angles[2])
    result = shifted(pose, Direction.FORWARD, 1.0, tilt=True)
    assert result.z == pytest.approx(pose.z + 1.0, abs=0.001)
    assert (result.x, result.y) == (pose.x, pose.y)


@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.BACK])
def test_alt_never_touches_y(direction: Direction) -> None:
    """Высота меняет ``X`` и ``Z``, но не ``Y``."""
    pose = replace(ALT, ry=25.0)
    result = shifted(pose, direction, 2.5, tilt=True)
    assert result.y == pose.y
    assert result.x != pose.x
    assert abs(result.z - pose.z) == pytest.approx(2.5 * math.cos(math.radians(25.0)), abs=0.01)


def test_tilt_is_rounded_to_millimetres() -> None:
    result = shifted(ALT, Direction.FORWARD, 0.333, tilt=True)
    assert result.z == 50.333


def test_changed_fields_sees_height_on_tilt() -> None:
    assert changed_fields(ALT, shifted(ALT, Direction.FORWARD, 0.5, tilt=True)) == (Field.Z,)
