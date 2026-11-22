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

    С ``tilt=True`` (в интерфейсе — Alt) учитывается наклон ``RX``: шаг идёт
    по наклонной плоскости предмета, поэтому «вперёд» поднимает при ``RX > 0``
    и опускает при ``RX < 0``:

    * вдоль «вперёд/назад» — ``X`` на ``step · cos(RX)``, ``Z`` на ``step · sin(RX)``;
    * влево/вправо наклон не влияет: ``Y`` меняется полностью, ``Z`` — нет;
    * диагональ остаётся шагом: ``√((dx·cos)² + dy² + (dx·sin)²) = step``.

    Без ``tilt`` меняются только ``X`` и ``Y``, ``Z`` и углы остаются как были.
    """
    validate_step(step)
    dx, dy = _normalize(direction)
    if tilt:
        angle = math.radians(pose.rx)
        local_x = dx * math.cos(angle)
        local_z = dx * math.sin(angle)
    else:
        local_x, local_z = dx, 0.0
    world_dx, world_dy = _rotate(local_x * step, dy * step, pose.rz)
    moved = replace(
        pose,
        x=rounded(pose.x + world_dx, COORD_DECIMALS),
        y=rounded(pose.y + world_dy, COORD_DECIMALS),
    )
    if local_z:
        moved = replace(moved, z=rounded(pose.z + local_z * step, COORD_DECIMALS))
    return moved


def _normalize(direction: Direction) -> tuple[float, float]:
    dx, dy = direction.axes
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _rotate(dx: float, dy: float, rz_degrees: float) -> tuple[float, float]:
    angle = math.radians(rz_degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a


def changed_fields(before: Pose, after: Pose, *, tolerance: float = TOLERANCE) -> tuple[Field, ...]:
    """Поля, которые действительно отличаются (в порядке панели)."""
    return tuple(
        field for field in PANEL_ORDER if abs(after.value(field) - before.value(field)) > tolerance
    )
