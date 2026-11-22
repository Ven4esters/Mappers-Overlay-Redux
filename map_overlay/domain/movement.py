"""Сдвиг позы с учётом поворота и сравнение полей."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Final

from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.formatting import rounded
from map_overlay.domain.pose import Pose
from map_overlay.errors import ValidationError

COORD_DECIMALS: Final = 3
"""Точность координат в панели LSP: миллиметры."""

MIN_STEP: Final = 0.01
MAX_STEP: Final = 100.0

TOLERANCE: Final = 0.0005
"""Половина третьего знака: меньше — это то же самое значение."""


def validate_step(step: float) -> float:
    """Проверить и нормализовать шаг сдвига в метрах.

    Raises:
        ValidationError: если шаг не конечный или вне диапазона.
    """
    if not math.isfinite(step):
        raise ValidationError("Шаг должен быть числом")
    if not MIN_STEP <= step <= MAX_STEP:
        raise ValidationError(f"Шаг должен быть от {MIN_STEP} до {MAX_STEP} м, получено {step:g}")
    return rounded(step, COORD_DECIMALS)


def shifted(pose: Pose, direction: Direction, step: float, *, tilt: bool = False) -> Pose:
    """Сдвинуть позу в направлении на шаг.

    Направление поворачивается на ``RZ``: ``+RZ`` — против часовой стрелки,
    ``−RZ`` — по часовой (так задано в игре). Поэтому при ``RZ = 90°`` «вперёд»
    ведёт туда, куда повёрнут предмет, а при нулевых углах правило простое:
    вперёд — ``X`` в плюс, влево — ``Y`` в плюс.

    Диагональ — это шаг по прямой: вектор ``(±1, ±1)`` нормализуется, поэтому
    предмет проходит ровно ``step`` метров, а не ``step · √2``.

    С ``tilt=True`` (в интерфейсе — режим наклона по ``Alt``) шаг считается
    в осях самого предмета и только потом переводится в мир: сначала ``RX``,
    затем ``RY``, затем ``RZ`` — в том же порядке, в каком их задаёт игра. Так
    шаг ложится в плоскость предмета:

    * поднимается и опускается та сторона, вокруг которой идёт наклон:
      ``RX`` наклоняет «влево-вправо», ``RY`` — «вперёд-назад»;
    * сторона, совпадающая с осью наклона, остаётся горизонтальной;
    * длина шага сохраняется: ``√(ΔX² + ΔY² + ΔZ²) = step``, диагональ тоже.

    Без ``tilt`` меняются только ``X`` и ``Y``, ``Z`` и углы остаются как были.
    """
    validate_step(step)
    dx, dy = _normalize(direction)
    if tilt:
        world_dx, world_dy, world_dz = _from_object_plane(dx, dy, pose)
    else:
        world_dx, world_dy = _rotate(dx, dy, pose.rz)
        world_dz = 0.0
    moved = replace(
        pose,
        x=rounded(pose.x + world_dx * step, COORD_DECIMALS),
        y=rounded(pose.y + world_dy * step, COORD_DECIMALS),
    )
    if world_dz:
        moved = replace(moved, z=rounded(pose.z + world_dz * step, COORD_DECIMALS))
    return moved


def _from_object_plane(dx: float, dy: float, pose: Pose) -> tuple[float, float, float]:
    """Единичный шаг из плоскости предмета в мир.

    Повороты применяются в порядке ``RX`` → ``RY`` → ``RZ``: ``RX`` наклоняет
    оси ``Y``/``Z``, ``RY`` — ``X``/``Z``, ``RZ`` доворачивает в плане.
    Поворот длину не меняет, поэтому шаг остаётся ровно ``step`` метров.
    """
    rx = math.radians(pose.rx)
    ry = math.radians(pose.ry)
    # RX: «вперёд-назад» — ось наклона, её шаг горизонтален; «влево-вправо» поднимается.
    x, y, z = dx, dy * math.cos(rx), dy * math.sin(rx)
    # RY: наклон вокруг оси «вперёд» поднимает уже сам «вперёд».
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    world_dx, world_dy = _rotate(x, y, pose.rz)
    return world_dx, world_dy, z


def _normalize(direction: Direction) -> tuple[float, float]:
    dx, dy = direction.axes
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _rotate(dx: float, dy: float, rz_degrees: float) -> tuple[float, float]:
    angle = math.radians(rz_degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a


def slope_directions(pose: Pose) -> tuple[Direction | None, Direction | None]:
    """Куда по плоскости предмета ведут «вверх» и «вниз».

    Возвращает направления с наибольшим подъёмом и спуском: по ним видно, какую
    клавишу нажимать, чтобы идти по наклону. Для горизонтальной плоскости —
    ``(None, None)``.
    """
    best_up: Direction | None = None
    best_down: Direction | None = None
    up = down = 0.0
    for direction in Direction:
        dx, dy = _normalize(direction)
        dz = _from_object_plane(dx, dy, pose)[2]
        if dz > up + TOLERANCE:
            up, best_up = dz, direction
        if dz < down - TOLERANCE:
            down, best_down = dz, direction
    return best_up, best_down


def changed_fields(before: Pose, after: Pose, *, tolerance: float = TOLERANCE) -> tuple[Field, ...]:
    """Поля, которые действительно отличаются (в порядке панели)."""
    return tuple(
        field for field in PANEL_ORDER if abs(after.value(field) - before.value(field)) > tolerance
    )
