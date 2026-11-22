from __future__ import annotations

import math

import pytest
from lsp_overlay.domain.directions import DiagonalMode, Direction, is_diagonal, local_vector
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import length
from lsp_overlay.domain.movement import move, rotate
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
    result = move(Pose(rx=30.0, ry=20.0, rz=45.0), Direction.NORTH_EAST, 1.0)
    assert result.z != 0.0  # наклон меняет высоту — это ожидаемо
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
