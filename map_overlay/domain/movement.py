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

    Диагональ — шаг по локальным осям: ``Y`` от ``RX``, ``X`` и ``Z`` от ``RY`` (см.
    ниже); длина шага равна ``шаг/√2``, а не ``step · √2``.

    С ``tilt=True`` (в интерфейсе — режим высоты, клавиша ``Alt``) меняется только
    смысл клавиш «вперёд-назад»: ``Num 8`` поднимает предмет по локальной оси ``Z``
    (с учётом ``RY``: ``ΔX = ±sin RY``, ``ΔZ = ±cos RY``), ``Num 2`` опускает.
    Остальные клавиши работают как обычно:
    ``Num 4/6`` — по горизонтали с поворотом от ``RZ``, диагонали — по формуле
    ``ΔX = ax·sin RY``, ``ΔY = ay·sin RX``, ``ΔZ = ax·cos RX·cos RY`` (см. ниже),
    поэтому они идут «линия к линии» при любом угле наклона, а не только при ``45°``.

    """
    validate_step(step)
    dx, dy = _normalize(direction)
    if tilt and direction in (Direction.FORWARD, Direction.BACK):
        # Режим высоты: шаг по локальной оси Z, повёрнутой на RY (плоскость X/Z).
        world_dx, world_dy, world_dz = _height_step(direction, pose)
    elif direction.is_diagonal:
        world_dx, world_dy, world_dz = _diagonal(direction, pose)
    else:
        world_dx, world_dy = _rotate(dx, dy, pose.rz)
        world_dz = 0.0
    moved = pose
    if world_dx:
        moved = replace(moved, x=rounded(pose.x + world_dx * step, COORD_DECIMALS))
    if world_dy:
        moved = replace(moved, y=rounded(pose.y + world_dy * step, COORD_DECIMALS))
    if world_dz:
        moved = replace(moved, z=rounded(pose.z + world_dz * step, COORD_DECIMALS))
    return moved


def _height_step(direction: Direction, pose: Pose) -> tuple[float, float, float]:
    """Шаг режима высоты: локальная ось ``Z``, повёрнутая на ``RY``.

    ``Δ_local = (0, 0, ±1)`` — «вверх/вниз» в осях предмета. Поворот вокруг ``Y``
    переводит его в мир в плоскости ``X/Z``:

    ```
    Ry(RY) = |  cos RY   0   sin RY |
             |    0      1      0   |
             | −sin RY   0   cos RY |

    ΔX = ±sin RY,   ΔY = 0,   ΔZ = ±cos RY
    ```

    Проверка на примере: ``RY = 10°``, шаг 3.0 →
    ``Δ = (3·sin 10°, 0, 3·cos 10°) = (0.5209, 0, 2.9544)``.

    При ``RY = 0`` это прежний шаг строго по ``Z``. ``RX`` и ``RZ`` на высоту не влияют:
    поворот вокруг ``X`` не меняет ``Z``-ось по величине, а ``RZ`` в формуле высоты не
    участвует.
    """
    sign = 1.0 if direction is Direction.FORWARD else -1.0
    angle = math.radians(pose.ry)
    return sign * math.sin(angle), 0.0, sign * math.cos(angle)


def _diagonal(direction: Direction, pose: Pose) -> tuple[float, float, float]:
    """Шаг диагональной клавиши: ``RX`` ведёт ``Y``, ``RY`` ведёт ``X`` и сжимает ``Z``.

    Формула пользователя (``L = шаг/√2``):

    ```
    X_new = X + ax · L · sin RY
    Y_new = Y + ay · L · sin RX
    Z_new = Z + ax · L · cos RX · cos RY
    ```

    ``ax = ±1`` — клавиша «вперёд/назад» (она же «вверх/вниз»), ``ay = ±1`` —
    «влево/вправо». Для ``Num 9`` (``ax = +1``, ``ay = −1``) это ровно формула из
    задания: ``X + L sin RY``, ``Y − L sin RX``, ``Z + L cos RX cos RY``.

    Проверка на примере: ``RX = 37°``, ``RY = 10°``, шаг 3.0 →
    ``Δ = (+0.368, −1.277, +1.668)``, то есть ``X −1848.974``, ``Y 415.251``,
    ``Z 130.494``.

    Свойства:

    * при ``RY = 0`` формула сводится к прежней: ``ΔX = 0``, поворот в плоскости
      ``Y/Z``; при ``RX = RY = 0`` — шаг ``шаг/√2`` строго по ``Z``;
    * наклон шага на экране (по ``Y`` и ``Z``) по-прежнему ``90° − RX``;
    * ``RY`` уводит шаг в глубину (``X``) и сжимает подъём множителем ``cos RY``;
    * длина шага остаётся ``шаг/√2``: поворот не растягивает вектор;
    * ``RZ`` в формулу не входит: диагонали не крутятся вместе с поворотом вокруг
      вертикали.
    """
    ax, ay = direction.axes
    arm = 1.0 / math.hypot(ax, ay)
    rx = math.radians(pose.rx)
    ry = math.radians(pose.ry)
    world_x = round(ax * arm * math.sin(ry), 12)
    world_y = round(ay * arm * math.sin(rx), 12)
    world_z = round(ax * arm * math.cos(rx) * math.cos(ry), 12)
    return world_x, world_y, world_z


def _normalize(direction: Direction) -> tuple[float, float]:
    dx, dy = direction.axes
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _rotate(dx: float, dy: float, rz_degrees: float) -> tuple[float, float]:
    angle = math.radians(rz_degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a


DIAGONAL_TITLES: Final[dict[Direction, str]] = {
    Direction.FORWARD_LEFT: "вверх-влево",
    Direction.FORWARD_RIGHT: "вверх-вправо",
    Direction.BACK_LEFT: "вниз-влево",
    Direction.BACK_RIGHT: "вниз-вправо",
}
"""Куда ведёт диагональная клавиша: ``RX`` ведёт ``Y``, ``RY`` — ``X`` и ``Z``."""

ALT_TITLES: Final[dict[Direction, str]] = {
    Direction.FORWARD: "вверх",
    Direction.BACK: "вниз",
}
"""Что делают ``Num 8`` и ``Num 2`` при включённом режиме высоты."""


def alt_hint() -> str:
    """Подсказка режима высоты: что делают клавиши при нажатом ``Alt``."""
    return "8 \u2191 вверх · 2 \u2193 вниз (ось Z, поворот RY)"


def changed_fields(before: Pose, after: Pose, *, tolerance: float = TOLERANCE) -> tuple[Field, ...]:
    """Поля, которые действительно отличаются (в порядке панели)."""
    return tuple(
        field for field in PANEL_ORDER if abs(after.value(field) - before.value(field)) > tolerance
    )
