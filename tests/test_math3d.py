from __future__ import annotations

import math
import pytest

from mapper_assist.math3d import (
    apply_local_move,
    apply_orientation_preset,
    euler_zxy_to_matrix,
    join_next_section,
    matrix_to_euler_zxy,
    measure_two_points,
    rotate_2d_gta,
    rotate_around_edge,
    rotate_local_3d,
    rotate_yaw,
    snap_yaw_to_anchor,
)
from mapper_assist.models import MoveSpace, Transform, format_number, normalize_angle_180, parse_number


def test_normalize_angle_180_wraparound() -> None:
    assert normalize_angle_180(0.0) == 0.0
    assert normalize_angle_180(-0.0) == 0.0
    assert normalize_angle_180(180.0) == 180.0
    assert normalize_angle_180(-180.0) == -180.0
    assert math.isclose(normalize_angle_180(190.0), -170.0, abs_tol=1e-9)
    assert math.isclose(normalize_angle_180(-190.0), 170.0, abs_tol=1e-9)
    assert math.isclose(normalize_angle_180(360.0 + 37.42), 37.42, abs_tol=1e-9)

    # Четыре поворота по +90° возвращают исходный кривой угол без накопления ошибки
    t = Transform(rz=37.42)
    for _ in range(4):
        t = rotate_yaw(t, 90.0)
    assert math.isclose(t.rz, 37.42, abs_tol=1e-9)


def test_gta_cardinal_directions() -> None:
    base = Transform(x=100.0, y=200.0, z=30.0, rz=0.0)
    # При RZ = 0°: Вперёд = +Y, Вправо = +X
    fw = apply_local_move(base, forward=2.5)
    assert (fw.x, fw.y, fw.z) == pytest.approx((100.0, 202.5, 30.0))

    rt = apply_local_move(base, right=1.5)
    assert (rt.x, rt.y, rt.z) == pytest.approx((101.5, 200.0, 30.0))

    # При RZ = +90°: Вперёд = -X (Запад), Вправо = +Y (Север)
    rot90 = Transform(x=100.0, y=200.0, z=30.0, rz=90.0)
    fw90 = apply_local_move(rot90, forward=2.0)
    assert (fw90.x, fw90.y) == pytest.approx((98.0, 200.0))

    rt90 = apply_local_move(rot90, right=3.0)
    assert (rt90.x, rt90.y) == pytest.approx((100.0, 203.0))


def test_arbitrary_angle_roundtrip_and_flipped_horizontal_safety() -> None:
    # Объект перевёрнут вверх ногами (RY=180°) и стоит под кривым углом 37.42°
    start = Transform(x=-412.35, y=1128.80, z=45.12, rx=0.0, ry=180.0, rz=37.42)

    # В режиме OBJECT_HORIZONTAL сдвиг Вверх идёт строго в небо (+Z), а не под землю!
    lifted = apply_local_move(start, right=1.25, forward=-0.6, up=0.5, mode=MoveSpace.OBJECT_HORIZONTAL)
    assert lifted.z == pytest.approx(45.62)
    assert lifted.ry == pytest.approx(180.0)
    assert lifted.rz == pytest.approx(37.42)

    # Обратный сдвиг возвращает ровно в исходные координаты
    returned = apply_local_move(lifted, right=-1.25, forward=0.6, up=-0.5, mode=MoveSpace.OBJECT_HORIZONTAL)
    assert (returned.x, returned.y, returned.z) == pytest.approx((start.x, start.y, start.z))


def test_anchor_horizontal_space() -> None:
    # Стул повёрнут на -23°, но двигаем его параллельно стене комнаты (anchor = 35°)
    chair = Transform(x=10.0, y=20.0, z=5.0, rz=-23.0)
    moved = apply_local_move(chair, right=2.0, mode=MoveSpace.ANCHOR_HORIZONTAL, anchor_rz=35.0)
    exp_dx, exp_dy = rotate_2d_gta(2.0, 0.0, 35.0)
    assert moved.x == pytest.approx(10.0 + exp_dx)
    assert moved.y == pytest.approx(20.0 + exp_dy)
    assert moved.rz == pytest.approx(-23.0)


def test_3d_tilted_movement_and_gimbal_lock() -> None:
    # Рампа с подъёмом RX = +30° при RZ = 0°: движение вперёд на 2 м поднимает Z на 1 м
    ramp = Transform(x=0.0, y=0.0, z=10.0, rx=30.0, ry=0.0, rz=0.0)
    slid = apply_local_move(ramp, forward=2.0, mode=MoveSpace.OBJECT_3D)
    assert slid.z == pytest.approx(11.0)
    assert slid.y == pytest.approx(2.0 * math.cos(math.radians(30.0)))

    # Проверка отсутствия потери угла при положении плашмя (RX = +90° и -90°)
    for flat_rx in (90.0, -90.0):
        m = euler_zxy_to_matrix(flat_rx, 0.0, -64.5)
        rx, ry, rz = matrix_to_euler_zxy(m)
        assert rx == pytest.approx(flat_rx)
        assert ry == pytest.approx(0.0)
        assert rz == pytest.approx(-64.5)

    # Обычный 3D roundtrip
    t3d = Transform(rx=15.0, ry=-25.0, rz=112.0)
    t_rot = rotate_local_3d(t3d, delta_rz=40.0)
    t_back = rotate_local_3d(t_rot, delta_rz=-40.0)
    assert (t_back.rx, t_back.ry, t_back.rz) == pytest.approx((t3d.rx, t3d.ry, t3d.rz), abs=1e-6)


def test_orientation_presets_preserve_rz() -> None:
    wall = Transform(x=5.0, y=6.0, z=7.0, rx=12.0, ry=-4.0, rz=-134.25)
    flipped = apply_orientation_preset(wall, "upside_down_roll")
    assert (flipped.rx, flipped.ry, flipped.rz) == pytest.approx((0.0, 180.0, -134.25))

    flat = apply_orientation_preset(flipped, "flat_back")
    assert (flat.rx, flat.ry, flat.rz) == pytest.approx((90.0, 0.0, -134.25))

    upright = apply_orientation_preset(flat, "upright")
    assert (upright.rx, upright.ry, upright.rz) == pytest.approx((0.0, 0.0, -134.25))


def test_snap_yaw_to_anchor() -> None:
    obj = Transform(rz=12.0)
    snapped = snap_yaw_to_anchor(obj, anchor_rz=135.0, offset_deg=90.0)
    # 135 + 90 = 225 -> -135 в диапазоне [-180, 180]
    assert snapped.rz == pytest.approx(-135.0)


def test_rotate_around_edge_keeps_edge_stationary() -> None:
    # Стена шириной 2.4 м (правый край +1.2 м) под углом 28.5°
    wall = Transform(x=50.0, y=-30.0, z=12.0, rz=28.5)
    edge_dx1, edge_dy1 = rotate_2d_gta(1.2, 0.0, wall.rz)
    right_edge_before = (wall.x + edge_dx1, wall.y + edge_dy1)

    turned = rotate_around_edge(wall, delta_rz=90.0, edge_right=1.2, edge_forward=0.0)
    edge_dx2, edge_dy2 = rotate_2d_gta(1.2, 0.0, turned.rz)
    right_edge_after = (turned.x + edge_dx2, turned.y + edge_dy2)

    assert right_edge_after == pytest.approx(right_edge_before, abs=1e-9)
    assert turned.rz == pytest.approx(118.5)


def test_join_next_section_straight_and_l_corner() -> None:
    # Секция забора шириной 2.0 м под углом 37°
    sec1 = Transform(x=10.0, y=20.0, z=5.0, rz=37.0)
    sec1_right = (
        sec1.x + rotate_2d_gta(1.0, 0.0, sec1.rz)[0],
        sec1.y + rotate_2d_gta(1.0, 0.0, sec1.rz)[1],
    )

    # 1) Прямое продолжение стены (0°)
    sec2_straight = join_next_section(sec1, section_size=2.0, direction="right", turn_deg=0.0)
    sec2_left = (
        sec2_straight.x + rotate_2d_gta(-1.0, 0.0, sec2_straight.rz)[0],
        sec2_straight.y + rotate_2d_gta(-1.0, 0.0, sec2_straight.rz)[1],
    )
    assert sec2_left == pytest.approx(sec1_right, abs=1e-9)

    # 2) Г-образный угол +90°: левый край новой секции идеально совпадает с правым краем первой!
    sec2_corner = join_next_section(sec1, section_size=2.0, direction="right", turn_deg=90.0)
    sec2_corner_left = (
        sec2_corner.x + rotate_2d_gta(-1.0, 0.0, sec2_corner.rz)[0],
        sec2_corner.y + rotate_2d_gta(-1.0, 0.0, sec2_corner.rz)[1],
    )
    assert sec2_corner_left == pytest.approx(sec1_right, abs=1e-9)
    assert sec2_corner.rz == pytest.approx(127.0)


def test_measure_two_points_ruler() -> None:
    a = Transform(x=10.0, y=20.0, z=5.0)
    b = Transform(x=13.0, y=24.0, z=7.0)  # dx=3, dy=4, dz=2 -> 2D dist = 5.0
    m = measure_two_points(a, b)
    assert m.distance_2d == pytest.approx(5.0)
    assert m.dz == pytest.approx(2.0)
    assert (m.midpoint.x, m.midpoint.y, m.midpoint.z) == pytest.approx((11.5, 22.0, 6.0))

    # Проверим, что смещение вдоль rz_along_x на +5 м из A попадает точно в B
    moved = apply_local_move(
        Transform(x=a.x, y=a.y, z=a.z, rz=m.rz_along_x),
        right=5.0,
        mode=MoveSpace.OBJECT_HORIZONTAL,
    )
    assert (moved.x, moved.y) == pytest.approx((b.x, b.y), abs=1e-7)


def test_number_parse_and_format() -> None:
    assert parse_number("  -1245,678 ") == pytest.approx(-1245.678)
    assert parse_number("+0.000") == 0.0
    assert format_number(-0.0000001, decimals=4) == "0"
    assert format_number(123.4500, decimals=4) == "123.45"
    assert format_number(-179.9999, decimals=3) == "-180"
