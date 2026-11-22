"""Стык двух предметов: буква Г, буква Т и точность контакта."""

from __future__ import annotations

import math

import pytest
from lsp_overlay.domain.catalog import ObjectSpec
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import rotation_matrix, transform
from lsp_overlay.domain.join import (
    CORNER_ANGLE,
    MAX_JOIN_ANGLE,
    MITRE_ANGLE,
    TEE_ANGLE,
    AcrossField,
    JoinRequest,
    JoinScheme,
    JoinSide,
    across_of,
    join_pose,
    local_offset,
)
from lsp_overlay.domain.pose import Pose

WALL = ObjectSpec(name="Стена", length=4.3, width=2.5, thickness=0.2)
FENCE = ObjectSpec(name="Забор", length=2.0, width=1.2, thickness=0.1)
BASE = Pose(x=0.0, y=0.0, z=1.0, rz=0.0)


def corner(angle: float = CORNER_ANGLE, side: JoinSide = JoinSide.RIGHT) -> JoinRequest:
    return JoinRequest(scheme=JoinScheme.CORNER, angle=angle, side=side)


def near_corner(
    spec: ObjectSpec, target: Pose, angle: float, side: JoinSide, base_rz: float
) -> tuple[float, float]:
    """Мировой угол B «торец + внешняя грань» — он должен лежать на угле A."""
    matrix = rotation_matrix(0.0, 0.0, base_rz)
    phi = math.radians(angle)
    u = transform((-side.turn * math.sin(phi), math.cos(phi), 0.0), matrix)
    v = transform((side.turn * math.cos(phi), math.sin(phi), 0.0), matrix)
    return (
        target.x - spec.length / 2.0 * u[0] + across_of(spec) / 2.0 * v[0],
        target.y - spec.length / 2.0 * u[1] + across_of(spec) / 2.0 * v[1],
    )


def test_corner_90_right_puts_second_object_flush() -> None:
    target = join_pose(BASE, WALL, WALL, corner())
    assert target.x == pytest.approx(0.1 + 2.15)
    assert target.y == pytest.approx(2.15 - 0.1)
    assert target.rz == pytest.approx(-90.0)
    assert target.z == pytest.approx(BASE.z)


def test_corner_90_left_is_mirror() -> None:
    target = join_pose(BASE, WALL, WALL, corner(side=JoinSide.LEFT))
    assert target.x == pytest.approx(-2.25)
    assert target.y == pytest.approx(2.05)
    assert target.rz == pytest.approx(90.0)


def test_corner_uses_both_sizes() -> None:
    """Вторая деталь другой длины и толщины встаёт своим углом в угол первой."""
    target = join_pose(BASE, WALL, FENCE, corner())
    assert target.x == pytest.approx(0.1 + 1.0)
    assert target.y == pytest.approx(2.15 - 0.05)


def test_corner_45_touches_corner_exactly() -> None:
    target = join_pose(BASE, WALL, WALL, corner(MITRE_ANGLE))
    x, y = near_corner(WALL, target, MITRE_ANGLE, JoinSide.RIGHT, BASE.rz)
    assert x == pytest.approx(0.1)
    assert y == pytest.approx(2.15)


def test_corner_custom_angle_touches_corner_exactly() -> None:
    for angle in (30.0, 60.0, 135.0, 170.0):
        target = join_pose(BASE, WALL, FENCE, corner(angle))
        x, y = near_corner(FENCE, target, angle, JoinSide.RIGHT, BASE.rz)
        assert x == pytest.approx(0.1), angle
        assert y == pytest.approx(2.15), angle


def test_corner_keeps_contact_for_rotated_base() -> None:
    base = Pose(x=250.0, y=-810.0, z=30.0, rz=37.0)
    target = join_pose(base, WALL, FENCE, corner(MITRE_ANGLE))
    radians = math.radians(base.rz)
    corner_x, corner_y = 0.1, 2.15
    expected = (
        base.x + corner_x * math.cos(radians) - corner_y * math.sin(radians),
        base.y + corner_x * math.sin(radians) + corner_y * math.cos(radians),
    )
    x, y = near_corner(FENCE, target, MITRE_ANGLE, JoinSide.RIGHT, base.rz)
    assert x == pytest.approx(expected[0])
    assert y == pytest.approx(expected[1])


def test_tee_presses_end_into_side() -> None:
    target = join_pose(BASE, WALL, FENCE, JoinRequest(scheme=JoinScheme.TEE))
    assert target.x == pytest.approx(0.1 + 1.0)
    assert target.y == pytest.approx(0.0)
    assert target.rz == pytest.approx(-90.0)
    assert target.z == pytest.approx(BASE.z)


def test_tee_ignores_angle_and_keeps_right_angle() -> None:
    request = JoinRequest(scheme=JoinScheme.TEE, angle=MITRE_ANGLE, side=JoinSide.LEFT)
    target = join_pose(BASE, WALL, FENCE, request)
    assert target.rz == pytest.approx(TEE_ANGLE)
    assert target.x == pytest.approx(-(0.1 + 1.0))


def test_second_object_never_overlaps_first() -> None:
    """Угол B касается A, но тела не пересекаются: точка контакта чуть сдвинута внутрь B."""
    target = join_pose(BASE, FENCE, FENCE, corner(MITRE_ANGLE))
    x, y = near_corner(FENCE, target, MITRE_ANGLE, JoinSide.RIGHT, BASE.rz)
    assert x == pytest.approx(0.05)
    assert y == pytest.approx(1.0)
    # центр B ушёл от точки контакта наружу, то есть B целиком снаружи A
    assert target.x > 0.05
    assert target.y > 1.0


def test_join_uses_thickness_by_default() -> None:
    """Тонкая грань — то, чем детали сходятся: по умолчанию поперёк берётся толщина."""
    target = join_pose(BASE, WALL, WALL, corner())
    assert target.x == pytest.approx(0.1 + 2.15)


def test_join_can_use_width_as_across_size() -> None:
    target = join_pose(
        BASE, WALL, WALL, JoinRequest(scheme=JoinScheme.CORNER, across=AcrossField.WIDTH)
    )
    # ширина 2.5 вместо толщины 0.2: B отходит от оси A дальше
    assert target.x == pytest.approx(2.5 / 2.0 + 2.15)
    assert target.y == pytest.approx(2.15 - 2.5 / 2.0)


def test_flat_object_joins_end_to_end() -> None:
    """Плоская стена без толщины стыкуется торцом в торец по своей плоскости."""
    plate = ObjectSpec(name="Плита", length=2.73, width=2.5, thickness=0.0)
    x, y = local_offset(plate, plate, corner(90.0, JoinSide.RIGHT))
    assert x == pytest.approx(1.365)
    assert y == pytest.approx(1.365)


def test_corner_follows_rotated_base() -> None:
    """На карте предмет повёрнут «для ровности» — стык идёт по его граням."""
    base = Pose(x=-1847.342, y=420.077, z=128.316, rz=70.0)
    target = join_pose(base, WALL, WALL, corner(90.0, JoinSide.LEFT))
    radians = math.radians(base.rz)
    local_x, local_y = -(0.2 / 2.0) - 4.3 / 2.0, 4.3 / 2.0 - 0.2 / 2.0
    assert target.x == pytest.approx(
        base.x + local_x * math.cos(radians) - local_y * math.sin(radians)
    )
    assert target.y == pytest.approx(
        base.y + local_x * math.sin(radians) + local_y * math.cos(radians)
    )
    assert target.rz == pytest.approx(160.0)


def test_tilt_moves_second_object_vertically() -> None:
    """Наклон A (RX/RY) учитывается: смещение идёт по всем трём осям."""
    base = Pose(x=0.0, y=0.0, z=10.0, rx=15.0)
    target = join_pose(base, WALL, WALL, corner())
    assert target.z != pytest.approx(base.z)
    distance = math.dist((target.x, target.y, target.z), (base.x, base.y, base.z))
    local = math.hypot(0.2 / 2.0 + 4.3 / 2.0, 4.3 / 2.0 - 0.2 / 2.0)
    assert distance == pytest.approx(local)


def test_matches_hand_placed_example_from_game() -> None:
    """Сверка с ручной установкой игрока: A под 70°, стена 2.7 × 0.1, Г влево."""
    base = Pose(x=-1847.342, y=420.077, z=128.316, rz=70.0)
    wall = ObjectSpec(name="Стена March 0-64", length=2.7, width=2.5, thickness=0.1)
    target = join_pose(base, wall, wall, corner(90.0, JoinSide.LEFT))
    hand = Pose(x=-1849.037, y=419.168, z=128.316, rz=160.0)
    assert target.rz == pytest.approx(hand.rz)
    assert math.dist((target.x, target.y), (hand.x, hand.y)) == pytest.approx(0.038, abs=0.02)
    # угол B стоит ровно в угле A
    x, y = near_corner(wall, target, 90.0, JoinSide.LEFT, base.rz)
    radians = math.radians(base.rz)
    corner_x, corner_y = -0.05, 1.35
    expected = (
        base.x + corner_x * math.cos(radians) - corner_y * math.sin(radians),
        base.y + corner_x * math.sin(radians) + corner_y * math.cos(radians),
    )
    assert x == pytest.approx(expected[0], abs=1e-9)
    assert y == pytest.approx(expected[1], abs=1e-9)


def test_angles_are_normalized() -> None:
    base = Pose(x=0.0, y=0.0, z=0.0, rz=170.0)
    target = join_pose(base, WALL, WALL, corner(side=JoinSide.LEFT))
    assert -180.0 <= target.rz < 180.0
    assert target.rz == pytest.approx(-100.0)


def test_too_large_angle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JoinRequest(angle=MAX_JOIN_ANGLE + 1.0).validated()


def test_too_small_angle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        join_pose(BASE, WALL, WALL, JoinRequest(angle=1.0))


def test_unmeasured_object_is_rejected() -> None:
    bare = ObjectSpec(name="Пусто")
    with pytest.raises(ValidationError, match="длина"):
        join_pose(BASE, bare, WALL, corner())


def test_join_requires_measured_length() -> None:
    point = ObjectSpec(name="Точка", length=0.0, width=2.0, thickness=0.1)
    with pytest.raises(ValidationError, match="длина"):
        join_pose(BASE, WALL, point, JoinRequest(across=AcrossField.WIDTH))


def test_local_offset_is_planar_and_finite() -> None:
    x, y = local_offset(WALL, FENCE, JoinRequest(scheme=JoinScheme.TEE))
    assert math.isfinite(x) and math.isfinite(y)
    assert y == pytest.approx(0.0)
