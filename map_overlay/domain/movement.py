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

    С ``tilt=True`` (в интерфейсе — режим по экрану, клавиша ``Alt``) шаг идёт
    в плоскости экрана, а не в плоскости предмета:

    * ``Num 8`` — вверх-вправо, ``Num 2`` — вниз-влево;
    * ``Num 4`` — вверх-влево, ``Num 6`` — вниз-вправо;
    * диагонали клавиш дают чистые «вверх», «вниз», «влево», «вправо»;
    * ``X`` не меняется — в глубину шаг не уходит;
    * длина шага сохраняется: ``√(ΔY² + ΔZ²) = step``, диагональ тоже.

    Углы ``RX``/``RY``/``RZ`` на этот режим не влияют: экранные оси заданы
    камерой, а не поворотом предмета. Без ``tilt`` меняются только ``X`` и ``Y``,
    ``Z`` и углы остаются как были.
    """
    validate_step(step)
    dx, dy = _normalize(direction)
    if tilt:
        world_dx, world_dy, world_dz = _from_screen(dx, dy)
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


def _from_screen(dx: float, dy: float) -> tuple[float, float, float]:
    """Единичный шаг в плоскости экрана в мировых осях ``(X, Y, Z)``.

    Камера смотрит вдоль ``X``, поэтому на экране вправо — это ``−Y``, а вверх —
    ``+Z``. Клавиши задают не оси, а диагонали экрана (``Num 8`` — вверх-вправо,
    ``Num 4`` — вверх-влево), то есть карта повёрнута на 45°:

    * ``Num 8`` → ``(−1, +1)``: ``ΔY −``, ``ΔZ +``;
    * ``Num 2`` → ``(+1, −1)``: ``ΔY +``, ``ΔZ −``;
    * ``Num 4`` → ``(+1, +1)``: ``ΔY +``, ``ΔZ +``;
    * ``Num 6`` → ``(−1, −1)``: ``ΔY −``, ``ΔZ −``;
    * диагонали клавиш попадают на чистые оси экрана.

    Сумма квадратов всегда равна единице, поэтому длина шага сохраняется.
    ``X`` не меняется: в глубину шаг не уходит.
    """
    root = math.sqrt(2.0)
    world_dy = (-dx + dy) / root
    world_dz = (dx + dy) / root
    return 0.0, world_dy, world_dz


def _normalize(direction: Direction) -> tuple[float, float]:
    dx, dy = direction.axes
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _rotate(dx: float, dy: float, rz_degrees: float) -> tuple[float, float]:
    angle = math.radians(rz_degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a


SCREEN_TITLES: Final[dict[Direction, str]] = {
    Direction.FORWARD: "вверх-вправо",
    Direction.BACK: "вниз-влево",
    Direction.LEFT: "вверх-влево",
    Direction.RIGHT: "вниз-вправо",
    Direction.FORWARD_LEFT: "вверх",
    Direction.FORWARD_RIGHT: "вправо",
    Direction.BACK_LEFT: "влево",
    Direction.BACK_RIGHT: "вниз",
}
"""Куда ведёт направление в режиме по экрану."""

SCREEN_GLYPHS: Final[dict[Direction, str]] = {
    Direction.FORWARD: "\u2197",
    Direction.BACK: "\u2199",
    Direction.LEFT: "\u2196",
    Direction.RIGHT: "\u2198",
    Direction.FORWARD_LEFT: "\u2191",
    Direction.FORWARD_RIGHT: "\u2192",
    Direction.BACK_LEFT: "\u2190",
    Direction.BACK_RIGHT: "\u2193",
}
"""Значки направлений на экране: те же клавиши, но другая сторона."""


def screen_hint() -> str:
    """Короткая подсказка «клавиша — куда» для режима по экрану."""
    return "8 \u2197 · 4 \u2196 · 2 \u2199 · 6 \u2198"


def changed_fields(before: Pose, after: Pose, *, tolerance: float = TOLERANCE) -> tuple[Field, ...]:
    """Поля, которые действительно отличаются (в порядке панели)."""
    return tuple(
        field for field in PANEL_ORDER if abs(after.value(field) - before.value(field)) > tolerance
    )
