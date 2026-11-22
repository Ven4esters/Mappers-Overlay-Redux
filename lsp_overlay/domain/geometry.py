"""Трёхмерная геометрия: матрица поворота и её применение к вектору.

Соглашения (см. ``docs/adr/0002-rotation-all-axes.md``):

* мировые оси GTA V — ``+X`` восток, ``+Y`` север, ``+Z`` вверх;
* углы ``RX``/``RY``/``RZ`` — градусы, положительное направление — против часовой
  стрелки при взгляде с положительного конца оси;
* матрица поворота собирается как ``Rz @ Ry @ Rx``: сначала наклон (RX), затем
  крен (RY), затем поворот вокруг вертикали (RZ). Именно в таком порядке GTA V
  применяет углы к пропу.
* локальные оси предмета: ``+X`` — вправо, ``+Y`` — вперёд (куда смотрит проп),
  ``+Z`` — вверх.
"""

from __future__ import annotations

import math

Vec3 = tuple[float, float, float]
Matrix3 = tuple[Vec3, Vec3, Vec3]

FULL_TURN = 360.0
HALF_TURN = 180.0


def wrap_angle(degrees: float) -> float:
    """Приводит угол к диапазону ``[-180, 180)`` — как в панели LSP.

    >>> wrap_angle(190.0)
    -170.0
    >>> wrap_angle(-180.0)
    -180.0
    """
    if not math.isfinite(degrees):
        raise ValueError("угол должен быть конечным числом")
    shifted = (degrees + HALF_TURN) % FULL_TURN - HALF_TURN
    return round(shifted, 6) + 0.0  # + 0.0 убирает «-0.0» из вывода


def _matrix_multiply(left: Matrix3, right: Matrix3) -> Matrix3:
    rows: list[Vec3] = []
    for row in left:
        new_row = tuple(
            sum(row[index] * right[index][column] for index in range(3)) for column in range(3)
        )
        rows.append((new_row[0], new_row[1], new_row[2]))
    return (rows[0], rows[1], rows[2])


def _rotation_x(degrees: float) -> Matrix3:
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return ((1.0, 0.0, 0.0), (0.0, cos, -sin), (0.0, sin, cos))


def _rotation_y(degrees: float) -> Matrix3:
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return ((cos, 0.0, sin), (0.0, 1.0, 0.0), (-sin, 0.0, cos))


def _rotation_z(degrees: float) -> Matrix3:
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return ((cos, -sin, 0.0), (sin, cos, 0.0), (0.0, 0.0, 1.0))


def rotation_matrix(
    rx_degrees: float = 0.0, ry_degrees: float = 0.0, rz_degrees: float = 0.0
) -> Matrix3:
    """Матрица перехода из локальных осей предмета в мировые: ``M = Rz @ Ry @ Rx``."""
    return _matrix_multiply(
        _rotation_z(rz_degrees),
        _matrix_multiply(_rotation_y(ry_degrees), _rotation_x(rx_degrees)),
    )


def transform(vector: Vec3, matrix: Matrix3) -> Vec3:
    """Умножает матрицу на вектор-столбец."""
    return (
        matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
        matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
        matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
    )


def inverse_transform(vector: Vec3, matrix: Matrix3) -> Vec3:
    """Переводит мировой вектор в локальные оси предмета.

    Матрица поворота ортогональна, поэтому обратная к ней — транспонированная.
    """
    return (
        matrix[0][0] * vector[0] + matrix[1][0] * vector[1] + matrix[2][0] * vector[2],
        matrix[0][1] * vector[0] + matrix[1][1] * vector[1] + matrix[2][1] * vector[2],
        matrix[0][2] * vector[0] + matrix[1][2] * vector[1] + matrix[2][2] * vector[2],
    )


def length(vector: Vec3) -> float:
    """Длина вектора."""
    return math.sqrt(sum(component * component for component in vector))


def normalize_diagonal(vector: Vec3) -> Vec3:
    """Нормирует вектор в плоскости XY так, чтобы диагональ имела ту же длину."""
    planar = math.hypot(vector[0], vector[1])
    if planar == 0.0:
        return vector
    scale = 1.0 / planar
    return (vector[0] * scale, vector[1] * scale, vector[2])


def add_scaled(origin: Vec3, vector: Vec3, scale: float) -> Vec3:
    """Возвращает ``origin + vector * scale``."""
    return (
        origin[0] + vector[0] * scale,
        origin[1] + vector[1] * scale,
        origin[2] + vector[2] * scale,
    )
