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

    С ``tilt=True`` (в интерфейсе — режим высоты, клавиша ``Alt``) меняется только
    смысл клавиш «вперёд-назад»: ``Num 8`` поднимает предмет (``Z`` в плюс),
    ``Num 2`` опускает (``Z`` в минус). Остальные клавиши работают как обычно:
    ``Num 4/6`` — по горизонтали с поворотом от ``RZ``, диагонали — по осям предмета
    (``P_new = P + Rx(RX) · Δ_local``), поэтому они идут «линия к линии» при любом
    угле наклона, а не только при ``45°``.

    """
    validate_step(step)
    dx, dy = _normalize(direction)
    if tilt and direction in (Direction.FORWARD, Direction.BACK):
        # Режим высоты: «вперёд-назад» превращается в «вверх-вниз» по Z.
        world_dx, world_dy = 0.0, 0.0
        world_dz = 1.0 if direction is Direction.FORWARD else -1.0
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


def _diagonal(direction: Direction, pose: Pose) -> tuple[float, float, float]:
    """Шаг диагональной клавиши: локальное смещение, повёрнутое на ``RX``.

    Формула шага — ``P_new = P + Rx(RX) · Δ_local``. Смещение задаётся **в осях
    предмета**, где ``X`` — вперёд, ``Y`` — влево, ``Z`` — вверх, а диагональ — это
    ``(0, ±1, ±1)``, нормированная к единице: ``Δ_local = (0, ay, ax) / √2``.

    Дальше оно поворачивается матрицей поворота предмета вокруг ``X``:

    ```
    Rx = | 1     0       0    |
         | 0  cos RX  −sin RX  |
         | 0  sin RX   cos RX  |
    ```

    то есть ``ΔY = ay·cos RX − ax·sin RX``, ``ΔZ = ay·sin RX + ax·cos RX``, ``ΔX = 0``.

    Свойства:

    * ``RX = 0`` — привычные ``0.354 / 0.354`` при шаге 0.5 м: шаг не изменился;
    * при любом угле длина шага равна шагу (поворот не растягивает вектор);
    * диагонали поворачиваются **вместе с предметом**, поэтому предмет каждый раз
      смещается на одну и ту же величину в своих осях — «линия к линии», без съезда;
    * соседние диагонали остаются перпендикулярными при любом угле;
    * ``X`` (глубина) не меняется: поворот вокруг неё не даёт компоненты по ``X``.
    """
    ax, ay = direction.axes
    length = math.hypot(ax, ay)
    local_y, local_z = ay / length, ax / length
    angle = math.radians(pose.rx)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    world_y = round(local_y * cos_a - local_z * sin_a, 12)
    world_z = round(local_y * sin_a + local_z * cos_a, 12)
    return 0.0, world_y, world_z


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
"""Куда ведёт диагональная клавиша: по осям предмета (``Y`` и ``Z``, поворот на ``RX``)."""

ALT_TITLES: Final[dict[Direction, str]] = {
    Direction.FORWARD: "вверх",
    Direction.BACK: "вниз",
}
"""Что делают ``Num 8`` и ``Num 2`` при включённом режиме высоты."""


def alt_hint() -> str:
    """Подсказка режима высоты: что делают клавиши при нажатом ``Alt``."""
    return "8 \u2191 вверх · 2 \u2193 вниз"


def changed_fields(before: Pose, after: Pose, *, tolerance: float = TOLERANCE) -> tuple[Field, ...]:
    """Поля, которые действительно отличаются (в порядке панели)."""
    return tuple(
        field for field in PANEL_ORDER if abs(after.value(field) - before.value(field)) > tolerance
    )
