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

    Диагональ — шаг по локальной плоскости ``X/Z`` с поворотом на ``RX`` (см. ниже);
    длина шага равна шагу, а не ``step · √2``.

    С ``tilt=True`` (в интерфейсе — режим высоты, клавиша ``Alt``) меняется только
    смысл клавиш «вперёд-назад»: ``Num 8`` поднимает предмет по локальной оси ``Z``
    (с учётом ``RY``: ``ΔX = ±sin RY``, ``ΔZ = ±cos RY``), ``Num 2`` опускает.
    Остальные клавиши работают как обычно:
    ``Num 4/6`` — по горизонтали с поворотом от ``RZ``, диагонали — поворот в
    плоскости ``Y/Z`` (``P_new = P + Rx(RX) · Δ_local``, ``X`` не меняется), поэтому
    они идут «линия к линии» при любом угле наклона, а не только при ``45°``.

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
    """Шаг диагональной клавиши: поворот в плоскости ``Y/Z``, ``X`` не меняется.

    Формула пользователя — ``P_new = P + Rx(RX) · Δ_local`` в плоскости ``Y/Z``:

    ```
    X_new = X
    Y_new = Y − Δz · sin RX
    Z_new = Z + Δz · cos RX        Δz = ax · шаг/√2
    ```

    Здесь ``ax = ±1`` — ось клавиши «вперёд/назад» (она же «вверх/вниз»), ``ay = ±1`` —
    «влево/вправо». Знак ``Y`` берётся от ``ay``, знак ``Z`` — от ``ax``:

    ```
    ΔY = ay · (шаг/√2) · sin RX
    ΔZ = ax · (шаг/√2) · cos RX
    ```

    Так расчёт совпадает с присланным примером: шаг 2.0, ``RX = 37°`` дают
    ``ΔY = −0.851``, ``ΔZ = +1.129`` при неизменном ``X``.

    Свойства:

    * ``X`` (глубина) не меняется — поворот вокруг ``X`` её не трогает;
    * наклон шага на экране равен ``90° − RX``: при ``RX = 45°`` это привычные 45°,
      при ``RX = 90°`` — горизонталь, при ``RX = 0`` — вертикаль;
    * длина шага равна ``шаг/√2`` (в плоскости ``Y/Z`` вектор поворачивается, а не
      растягивается); ``RZ`` в формулу не входит.
    """
    ax, ay = direction.axes
    length = math.hypot(ax, ay)
    arm = 1.0 / length
    angle = math.radians(pose.rx)
    world_y = round(ay * arm * math.sin(angle), 12)
    world_z = round(ax * arm * math.cos(angle), 12)
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
"""Куда ведёт диагональная клавиша: поворот в плоскости ``Y/Z`` на угол ``RX``."""

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
