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
    ``Num 4/6`` — по горизонтали с поворотом от ``RZ``, диагонали — по плоскости
    предмета (``ΔY = ∓cos RX``, ``ΔZ = ±sin RX``), поэтому они идут «линия к линии»
    при любом угле наклона, а не только при ``45°``.

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
    """Единичный шаг диагональной клавиши **по плоскости предмета**.

    Диагональ должна идти по поверхности предмета, а не под фиксированными 45°.
    Плоскость, наклонённая на ``RX``, содержит направление ``(0, −cos RX, sin RX)``
    (и симметричные), поэтому величины компонент берутся из угла наклона:

    * ``Num 9`` → ``(0, −cos RX, +sin RX)`` — вверх-вправо;
    * ``Num 7`` → ``(0, +cos RX, +sin RX)`` — вверх-влево;
    * ``Num 1`` → ``(0, +cos RX, −sin RX)`` — вниз-влево;
    * ``Num 3`` → ``(0, −cos RX, −sin RX)`` — вниз-вправо.

    При ``RX = 45°`` это привычные 0.354 на 0.354, а при ``RX = 37°`` — 0.399 на 0.301,
    то есть ровно по наклону. Длина шага равна единице при любом угле: ``cos² + sin² = 1``.
    ``X`` не меняется. На ровном предмете (``RX = 0``) диагональ ложится в горизонталь:
    у плоской поверхности вертикальной составляющей нет.
    """
    ax, ay = direction.axes
    rx = math.radians(pose.rx)
    return 0.0, ay * math.cos(rx), ax * math.sin(rx)


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
"""Куда ведёт диагональная клавиша: она идёт по плоскости предмета (``Y`` и ``Z``)."""

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
