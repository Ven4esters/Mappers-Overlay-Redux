from __future__ import annotations

from dataclasses import dataclass
import math

from .models import MoveSpace, Transform, clean_zero, normalize_angle_180


Matrix3x3 = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]

ORIENTATION_PRESETS: dict[str, tuple[float, float, str]] = {
    "upright": (0.0, 0.0, "Стоя (RX=0°, RY=0°)"),
    "upside_down_roll": (0.0, 180.0, "Вверх ногами через бок (RY=180°)"),
    "upside_down_pitch": (180.0, 0.0, "Вверх ногами через перёд (RX=180°)"),
    "flat_back": (90.0, 0.0, "Плашмя на спину (RX=+90°)"),
    "flat_forward": (-90.0, 0.0, "Плашмя лицом вниз (RX=-90°)"),
    "flat_right": (0.0, 90.0, "На правый бок (RY=+90°)"),
    "flat_left": (0.0, -90.0, "На левый бок (RY=-90°)"),
}


@dataclass(frozen=True)
class TwoPointMeasurement:
    """Результат замера геометрии между двумя точками A и B."""

    dx: float
    dy: float
    dz: float
    distance_2d: float
    distance_3d: float
    rz_along_x: float      # Угол RZ, если длина стены идёт вдоль локальной оси X пропа
    rz_look_along_y: float # Угол RZ, если перёд (+Y) пропа смотрит из A в B
    midpoint: Transform


def rotate_2d_gta(local_right: float, local_forward: float, rz_deg: float) -> tuple[float, float]:
    """
    Переводит горизонтальное смещение (вправо, вперёд) в мировые (dX, dY) GTA V.

    В GTA V:
      +X = Восток, +Y = Север, +Z = Верх.
      Угол RZ (Heading) отсчитывается против часовой стрелки вокруг +Z:
        RZ = 0°   -> Вперёд = (0, +1), Вправо = (+1, 0)
        RZ = +90° -> Вперёд = (-1, 0), Вправо = (0, +1)
    """
    rad = math.radians(rz_deg)
    cos_z = math.cos(rad)
    sin_z = math.sin(rad)
    dx = local_right * cos_z - local_forward * sin_z
    dy = local_right * sin_z + local_forward * cos_z
    return clean_zero(dx), clean_zero(dy)


def mat_mul(a: Matrix3x3, b: Matrix3x3) -> Matrix3x3:
    """Умножение двух матриц 3x3."""
    return tuple(  # type: ignore[return-value]
        tuple(
            sum(a[row][k] * b[k][col] for k in range(3))
            for col in range(3)
        )
        for row in range(3)
    )


def euler_zxy_to_matrix(rx_deg: float, ry_deg: float, rz_deg: float) -> Matrix3x3:
    """
    Строит матрицу вращения R = R_z(rz) @ R_x(rx) @ R_y(ry), соответствующую
    стандартному порядку вращения сущностей GTA V / FiveM (rotationOrder = 2).
    Столбцы матрицы — единичные векторы Right, Forward, Up в мировых координатах.
    """
    rx = math.radians(rx_deg)
    ry = math.radians(ry_deg)
    rz = math.radians(rz_deg)

    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    r00 = cz * cy - sz * sx * sy
    r01 = -sz * cx
    r02 = cz * sy + sz * sx * cy

    r10 = sz * cy + cz * sx * sy
    r11 = cz * cx
    r12 = sz * sy - cz * sx * cy

    r20 = -cx * sy
    r21 = sx
    r22 = cx * cy

    return (
        (r00, r01, r02),
        (r10, r11, r12),
        (r20, r21, r22),
    )


def matrix_to_euler_zxy(m: Matrix3x3) -> tuple[float, float, float]:
    """
    Извлекает углы Эйлера (rx, ry, rz) в диапазоне [-180, 180] из матрицы ZXY,
    корректно обрабатывая положение «плашмя» (gimbal lock при rx = ±90°).
    """
    sin_x = max(-1.0, min(1.0, m[2][1]))
    rx_rad = math.asin(sin_x)
    cos_x = math.cos(rx_rad)

    if abs(cos_x) > 1e-6:
        rz_rad = math.atan2(-m[0][1], m[1][1])
        ry_rad = math.atan2(-m[2][0], m[2][2])
    else:
        # Gimbal lock: объект лежит строго плашмя (rx = +90° или -90°).
        # Фиксируем ry = 0° и выражаем весь горизонтальный поворот через rz.
        ry_rad = 0.0
        rz_rad = math.atan2(m[1][0], m[0][0])

    return (
        normalize_angle_180(math.degrees(rx_rad)),
        normalize_angle_180(math.degrees(ry_rad)),
        normalize_angle_180(math.degrees(rz_rad)),
    )


def apply_local_move(
    transform: Transform,
    right: float = 0.0,
    forward: float = 0.0,
    up: float = 0.0,
    mode: MoveSpace | str = MoveSpace.OBJECT_HORIZONTAL,
    anchor_rz: float = 0.0,
) -> Transform:
    """
    Сдвигает объект в выбранной системе координат и возвращает новый Transform.
    """
    space = MoveSpace(mode)

    if space == MoveSpace.WORLD:
        dx, dy, dz = right, forward, up
    elif space == MoveSpace.OBJECT_HORIZONTAL:
        dx, dy = rotate_2d_gta(right, forward, transform.rz)
        dz = up
    elif space == MoveSpace.ANCHOR_HORIZONTAL:
        dx, dy = rotate_2d_gta(right, forward, anchor_rz)
        dz = up
    elif space == MoveSpace.OBJECT_3D:
        mat = euler_zxy_to_matrix(transform.rx, transform.ry, transform.rz)
        dx = mat[0][0] * right + mat[0][1] * forward + mat[0][2] * up
        dy = mat[1][0] * right + mat[1][1] * forward + mat[1][2] * up
        dz = mat[2][0] * right + mat[2][1] * forward + mat[2][2] * up
    else:
        raise ValueError(f"Неизвестный режим движения: {mode}")

    return Transform(
        x=clean_zero(transform.x + dx),
        y=clean_zero(transform.y + dy),
        z=clean_zero(transform.z + dz),
        rx=transform.rx,
        ry=transform.ry,
        rz=transform.rz,
    ).normalized()


def rotate_yaw(transform: Transform, delta_rz: float) -> Transform:
    """
    Поворачивает объект вокруг вертикальной оси комнаты (Z) на delta_rz градусов,
    сохраняя текущие углы наклона RX и RY и нормализуя результат в [-180, 180].
    """
    return Transform(
        x=transform.x,
        y=transform.y,
        z=transform.z,
        rx=transform.rx,
        ry=transform.ry,
        rz=normalize_angle_180(transform.rz + delta_rz),
    )


def snap_yaw_to_anchor(transform: Transform, anchor_rz: float, offset_deg: float = 0.0) -> Transform:
    """
    Выставляет угол объекта строго под offset_deg (0°, ±45°, ±90°, 180°)
    относительно базового угла комнаты anchor_rz.
    """
    return Transform(
        x=transform.x,
        y=transform.y,
        z=transform.z,
        rx=transform.rx,
        ry=transform.ry,
        rz=normalize_angle_180(anchor_rz + offset_deg),
    )


def rotate_local_3d(
    transform: Transform,
    delta_rx: float = 0.0,
    delta_ry: float = 0.0,
    delta_rz: float = 0.0,
) -> Transform:
    """Честный локальный 3D-поворот вокруг собственных осей наклонённого объекта."""
    cur_mat = euler_zxy_to_matrix(transform.rx, transform.ry, transform.rz)
    delta_mat = euler_zxy_to_matrix(delta_rx, delta_ry, delta_rz)
    new_mat = mat_mul(cur_mat, delta_mat)
    nrx, nry, nrz = matrix_to_euler_zxy(new_mat)
    return Transform(
        x=transform.x,
        y=transform.y,
        z=transform.z,
        rx=nrx,
        ry=nry,
        rz=nrz,
    )


def apply_orientation_preset(transform: Transform, preset_key: str) -> Transform:
    """
    Устанавливает положение «Стоя», «Вверх ногами» или «Плашмя»,
    не сбивая горизонтальный разворот объекта в комнате (RZ).
    """
    if preset_key not in ORIENTATION_PRESETS:
        raise KeyError(f"Неизвестный пресет ориентации: {preset_key}")
    rx, ry, _ = ORIENTATION_PRESETS[preset_key]
    return Transform(
        x=transform.x,
        y=transform.y,
        z=transform.z,
        rx=normalize_angle_180(rx),
        ry=normalize_angle_180(ry),
        rz=normalize_angle_180(transform.rz),
    )


def rotate_around_edge(
    transform: Transform,
    delta_rz: float,
    edge_right: float = 0.0,
    edge_forward: float = 0.0,
) -> Transform:
    """
    Поворачивает объект на delta_rz градусов не вокруг его центра,
    а вокруг вынесенной точки (например, правого края +W/2 или левого края -W/2).
    Одновременно пересчитывает X, Y и RZ так, чтобы край остался на том же месте.
    """
    old_dx, old_dy = rotate_2d_gta(edge_right, edge_forward, transform.rz)
    pivot_x = transform.x + old_dx
    pivot_y = transform.y + old_dy

    new_rz = normalize_angle_180(transform.rz + delta_rz)
    new_dx, new_dy = rotate_2d_gta(edge_right, edge_forward, new_rz)

    return Transform(
        x=clean_zero(pivot_x - new_dx),
        y=clean_zero(pivot_y - new_dy),
        z=transform.z,
        rx=transform.rx,
        ry=transform.ry,
        rz=new_rz,
    )


def join_next_section(
    base: Transform,
    section_size: float,
    direction: str = "right",
    turn_deg: float = 0.0,
) -> Transform:
    """
    Рассчитывает координаты следующей секции (стены/забора/плиты) размером section_size,
    пристыкованной край-в-край к эталонному объекту base с возможностью поворота угла (0°, ±90°).

    direction:
      - "right"   : стыковка к правому краю (+X/2) секции
      - "left"    : стыковка к левому краю (-X/2) секции
      - "forward" : стыковка к переднему краю (+Y/2) секции
      - "back"    : стыковка к заднему краю (-Y/2) секции
    """
    half = section_size / 2.0
    offsets = {
        "right": (half, 0.0),
        "left": (-half, 0.0),
        "forward": (0.0, half),
        "back": (0.0, -half),
    }
    if direction not in offsets:
        raise ValueError(f"Неизвестное направление стыковки: {direction}")

    er, ef = offsets[direction]
    # Мировая точка края базовой секции
    dx1, dy1 = rotate_2d_gta(er, ef, base.rz)
    join_x = base.x + dx1
    join_y = base.y + dy1

    # Новый угол следующей секции и смещение её центра от точки стыка
    new_rz = normalize_angle_180(base.rz + turn_deg)
    dx2, dy2 = rotate_2d_gta(er, ef, new_rz)

    return Transform(
        x=clean_zero(join_x + dx2),
        y=clean_zero(join_y + dy2),
        z=base.z,
        rx=base.rx,
        ry=base.ry,
        rz=new_rz,
    )


def measure_two_points(point_a: Transform, point_b: Transform) -> TwoPointMeasurement:
    """
    Вычисляет расстояние и точные углы стены/линии между точками A и B.
    """
    dx = clean_zero(point_b.x - point_a.x)
    dy = clean_zero(point_b.y - point_a.y)
    dz = clean_zero(point_b.z - point_a.z)

    dist_2d = clean_zero(math.hypot(dx, dy))
    dist_3d = clean_zero(math.sqrt(dx * dx + dy * dy + dz * dz))

    if dist_2d < 1e-8:
        rz_x = normalize_angle_180(point_a.rz)
        rz_y = normalize_angle_180(point_a.rz)
    else:
        # Ось +X (вправо) смотрит из A в B: (cos(rz), sin(rz)) || (dx, dy)
        rz_x = normalize_angle_180(math.degrees(math.atan2(dy, dx)))
        # Ось +Y (вперёд) смотрит из A в B: (-sin(rz), cos(rz)) || (dx, dy)
        rz_y = normalize_angle_180(math.degrees(math.atan2(-dx, dy)))

    midpoint = Transform(
        x=clean_zero((point_a.x + point_b.x) / 2.0),
        y=clean_zero((point_a.y + point_b.y) / 2.0),
        z=clean_zero((point_a.z + point_b.z) / 2.0),
        rx=0.0,
        ry=0.0,
        rz=rz_x,
    )

    return TwoPointMeasurement(
        dx=dx,
        dy=dy,
        dz=dz,
        distance_2d=dist_2d,
        distance_3d=dist_3d,
        rz_along_x=rz_x,
        rz_look_along_y=rz_y,
        midpoint=midpoint,
    )
