from __future__ import annotations

import math

import pytest
from lsp_overlay.domain.directions import DiagonalMode, Direction, is_diagonal, local_vector
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import length
from lsp_overlay.domain.movement import InvertSigns, MoveSpace, move, rotate
from lsp_overlay.domain.pose import Axis, Pose

STRAIGHT_CASES = [
    (Direction.NORTH, (0.0, 2.0, 0.0)),
    (Direction.SOUTH, (0.0, -2.0, 0.0)),
    (Direction.EAST, (2.0, 0.0, 0.0)),
    (Direction.WEST, (-2.0, 0.0, 0.0)),
    (Direction.UP, (0.0, 0.0, 2.0)),
    (Direction.DOWN, (0.0, 0.0, -2.0)),
]


@pytest.mark.parametrize(("direction", "expected"), STRAIGHT_CASES)
def test_straight_directions_without_rotation(
    direction: Direction, expected: tuple[float, float, float]
) -> None:
    result = move(Pose(), direction, 2.0)
    assert result.position == pytest.approx(expected)


@pytest.mark.parametrize(
    "direction",
    [Direction.NORTH_EAST, Direction.SOUTH_EAST, Direction.SOUTH_WEST, Direction.NORTH_WEST],
)
def test_diagonal_has_requested_length(direction: Direction) -> None:
    result = move(Pose(), direction, 2.0, diagonal_mode=DiagonalMode.SAME_DISTANCE)
    delta = (
        result.x - 0.0,
        result.y - 0.0,
        result.z - 0.0,
    )
    assert length(delta) == pytest.approx(2.0)
    assert delta[0] != 0.0 and delta[1] != 0.0
    assert delta[2] == 0.0


def test_diagonal_same_step_mode_moves_step_on_each_axis() -> None:
    result = move(Pose(), Direction.NORTH_EAST, 2.0, diagonal_mode=DiagonalMode.SAME_STEP)
    assert result.position == pytest.approx((2.0, 2.0, 0.0))


def test_diagonal_does_not_touch_z_even_for_tilted_prop() -> None:
    """По умолчанию, как в первой версии, наклоны RX/RY не участвуют: шаг остаётся на полу."""
    result = move(Pose(rx=30.0, ry=20.0, rz=45.0), Direction.NORTH_EAST, 1.0)
    assert result.z == pytest.approx(0.0)
    tilted = move(Pose(rx=30.0, ry=20.0, rz=45.0), Direction.NORTH_EAST, 1.0, use_tilt=True)
    assert tilted.z != 0.0  # по плоскости наклонённой детали высота уже меняется
    assert is_diagonal(Direction.NORTH_EAST)


def test_move_follows_yaw_of_the_prop() -> None:
    pose = Pose(x=0.0, y=0.0, rz=90.0)
    result = move(pose, Direction.NORTH, 1.0)
    assert result.position == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)


def test_move_uses_tilt_when_enabled() -> None:
    pose = Pose(rx=90.0)
    result = move(pose, Direction.NORTH, 1.0, use_tilt=True)
    assert result.position == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)


def test_move_ignores_tilt_when_disabled() -> None:
    pose = Pose(rx=90.0)
    result = move(pose, Direction.NORTH, 1.0, use_tilt=False)
    assert result.position == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)


@pytest.mark.parametrize("yaw", [0.0, 45.0, 70.0, 90.0, 180.0, -120.0])
def test_world_frame_ignores_angle_of_the_prop(yaw: float) -> None:
    """Мировые оси: какой бы ни был угол, ↑ — это всегда +Y."""
    pose = Pose(x=10.0, y=20.0, rz=yaw)
    result = move(pose, Direction.NORTH, 1.5, frame=MoveSpace.WORLD)
    assert result.x == pytest.approx(10.0)
    assert result.y == pytest.approx(21.5)


def test_world_frame_ignores_tilt_and_keeps_height() -> None:
    """Наклон RX/RY тоже не мешает: шаг остаётся в плоскости пола."""
    pose = Pose(x=0.0, y=0.0, z=5.0, rx=12.0, ry=-8.0, rz=70.0)
    result = move(pose, Direction.EAST, 1.0, frame=MoveSpace.WORLD)
    assert (result.x, result.y, result.z) == pytest.approx((1.0, 0.0, 5.0))


def test_world_frame_can_be_turned_to_the_camera() -> None:
    """Поправка на камеру: при повороте осей на 45° «↑» идёт на северо-запад."""
    pose = Pose(rz=70.0)
    result = move(pose, Direction.NORTH, 2.0, frame=MoveSpace.WORLD, rotation=45.0)
    assert result.x == pytest.approx(-math.sqrt(2.0), abs=1e-9)
    assert result.y == pytest.approx(math.sqrt(2.0), abs=1e-9)
    assert move(pose, Direction.NORTH, 1.0, frame=MoveSpace.WORLD).y == pytest.approx(1.0)


def test_prop_frame_ignores_camera_correction() -> None:
    """В режиме «предмет» поправка на камеру не применяется: там угол предмета."""
    pose = Pose(rz=0.0)
    result = move(pose, Direction.NORTH, 1.0, frame=MoveSpace.OBJECT, rotation=45.0)
    assert result.y == pytest.approx(1.0)
    assert result.x == pytest.approx(0.0)


def test_prop_frame_recomputes_direction_after_turning() -> None:
    """Режим «предмет»: после поворота «вперёд» идёт уже по новой оси."""
    pose = Pose(rz=0.0)
    assert move(pose, Direction.NORTH, 1.0, frame=MoveSpace.OBJECT).y == pytest.approx(1.0)
    turned = rotate(pose, Axis.YAW, 90.0)
    assert move(turned, Direction.NORTH, 1.0, frame=MoveSpace.OBJECT).x == pytest.approx(-1.0)


def test_move_preserves_rotation() -> None:
    pose = Pose(rx=10.0, ry=20.0, rz=30.0)
    assert move(pose, Direction.EAST, 1.0).angles == pose.angles


@pytest.mark.parametrize("step", [0.0, -1.0, float("nan"), float("inf")])
def test_move_rejects_bad_step(step: float) -> None:
    with pytest.raises(ValidationError):
        move(Pose(), Direction.NORTH, step)


def test_rotate_normalizes_angle() -> None:
    assert rotate(Pose(rz=170.0), Axis.YAW, 20.0).rz == pytest.approx(-170.0)
    assert rotate(Pose(rz=-170.0), Axis.YAW, -20.0).rz == pytest.approx(170.0)


def test_rotate_keeps_position() -> None:
    pose = Pose(x=1.0, y=2.0, z=3.0, rz=10.0)
    rotated = rotate(pose, Axis.PITCH, 45.0)
    assert rotated.position == pose.position
    assert rotated.rx == pytest.approx(45.0)


def test_rotate_rejects_nonfinite_angle() -> None:
    with pytest.raises(ValidationError):
        rotate(Pose(), Axis.ROLL, float("nan"))


def test_all_ten_directions_have_vectors() -> None:
    assert len(Direction) == 10
    for direction in Direction:
        assert length(local_vector(direction)) > 0.0


def test_pose_fields_cannot_be_mutated() -> None:
    pose = Pose()
    with pytest.raises(AttributeError):
        pose.x = 5.0  # type: ignore[misc]


def test_rounding_matches_game_precision() -> None:
    pose = Pose(1.234567, -0.0000001, 2.0).rounded(4)
    assert pose.x == pytest.approx(1.2346)
    assert math.copysign(1.0, pose.y) > 0


def first_version_step(right: float, forward: float, yaw: float) -> tuple[float, float]:
    """Сдвиг из первой версии: ``mapper_assist/math3d.py::rotate_2d_gta``."""
    rad = math.radians(yaw)
    return (
        right * math.cos(rad) - forward * math.sin(rad),
        right * math.sin(rad) + forward * math.cos(rad),
    )


@pytest.mark.parametrize("yaw", [0.0, 45.0, 70.0, 90.0, 180.0, -120.0, 359.0])
@pytest.mark.parametrize(
    ("direction", "right", "forward"),
    [
        (Direction.NORTH, 0.0, 1.0),
        (Direction.SOUTH, 0.0, -1.0),
        (Direction.EAST, 1.0, 0.0),
        (Direction.WEST, -1.0, 0.0),
    ],
)
def test_cardinal_step_matches_the_first_version(
    yaw: float, direction: Direction, right: float, forward: float
) -> None:
    """Шаг по сторонам в точности повторяет формулу первой версии."""
    pose = Pose(x=0.0, y=0.0, z=3.0, rz=yaw)
    dx, dy = first_version_step(right, forward, yaw)
    result = move(pose, direction, 1.0)
    assert (result.x, result.y) == pytest.approx((dx, dy), abs=1e-12)
    assert result.z == pytest.approx(3.0)


def test_sideways_step_moves_both_axes_with_angle() -> None:
    """При угле 70° «влево» меняет и X, и Y — предмет едет ровно поперёк."""
    result = move(Pose(x=0.0, y=0.0, z=0.0, rz=70.0), Direction.WEST, 0.5)
    assert result.x == pytest.approx(-0.171, abs=1e-3)
    assert result.y == pytest.approx(-0.470, abs=1e-3)
    assert result.z == pytest.approx(0.0)


def test_diagonal_matches_the_first_version() -> None:
    """Диагональ под 45° в осях предмета: как формула v1 с единичным шагом по обеим осям."""
    yaw = 70.0
    half = 1.0 / math.sqrt(2.0)
    dx, dy = first_version_step(half, half, yaw)
    result = move(Pose(rz=yaw), Direction.NORTH_EAST, 1.0)
    assert (result.x, result.y) == pytest.approx((dx, dy), abs=1e-12)


def test_anchor_frame_keeps_direction_when_prop_turns() -> None:
    """Режим «якорь»: угол берётся не у предмета, поэтому поворот шаг не меняет."""
    first = move(Pose(rz=0.0), Direction.NORTH, 1.0, frame=MoveSpace.ANCHOR, anchor=70.0)
    second = move(Pose(rz=95.0), Direction.NORTH, 1.0, frame=MoveSpace.ANCHOR, anchor=70.0)
    assert (first.x, first.y) == pytest.approx((second.x, second.y), abs=1e-12)
    assert first.x == pytest.approx(-math.sin(math.radians(70.0)), abs=1e-12)


def test_anchor_frame_differs_from_object_frame() -> None:
    """Предмет повёрнут на 20°, якорь 0° — направления разные, но оба прямые."""
    pose = Pose(rz=20.0)
    by_object = move(pose, Direction.EAST, 1.0, frame=MoveSpace.OBJECT)
    by_anchor = move(pose, Direction.EAST, 1.0, frame=MoveSpace.ANCHOR, anchor=0.0)
    assert by_object.x == pytest.approx(math.cos(math.radians(20.0)), abs=1e-12)
    assert by_object.y == pytest.approx(math.sin(math.radians(20.0)), abs=1e-12)
    assert by_anchor.y == pytest.approx(0.0, abs=1e-12)


def test_invert_flags_mirror_axes() -> None:
    """Поправки направлений: «вправо» уводит влево, «вперёд» — назад."""
    pose = Pose(rz=0.0)
    mirrored = move(pose, Direction.EAST, 1.0, invert=InvertSigns(right=True))
    assert mirrored.x == pytest.approx(-1.0)
    signs = InvertSigns(forward=True)
    assert signs.any is True
    back = move(pose, Direction.NORTH, 1.0, invert=signs)
    assert back.y == pytest.approx(-1.0)
    assert InvertSigns().any is False
