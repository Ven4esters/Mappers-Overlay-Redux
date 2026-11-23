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
# Точность координат в панели LSP: миллиметры.

MIN_STEP: Final = 0.01
MAX_STEP: Final = 100.0

TOLERANCE: Final = 0.0005
# Половина третьего знака: меньше — это то же самое значение.


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

    Диагональ — по случаю: в горизонтали без наклона, в плоскости ``Y/Z`` при одном
    ``RX`` и ``Rx(RX)·Ry(RY)`` при обоих углах — кроме пары ``Num 7/3``, у которой и при
    двух углах работает формула плоскости ``Y/Z`` (см. ``_diagonal``).

    С ``tilt=True`` (в интерфейсе — режим высоты, клавиша ``Alt``) меняется только
    смысл клавиш «вперёд-назад»: ``Num 8`` поднимает предмет по локальной оси ``Z``
    (с учётом ``RY``: ``ΔX = ±sin RY``, ``ΔZ = ±cos RY``), ``Num 2`` опускает.
    Остальные клавиши работают как обычно:
    ``Num 4/6`` — по горизонтали с поворотом от ``RZ``; диагонали зависят от наклона:
    без наклона — обычная диагональ в горизонтали, только с ``RX`` — поворот в
    плоскости ``Y/Z``, с ``RX`` и ``RY`` — поворот ``Rx(RX) · Ry(RY)`` (см. ниже).

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
    """Шаг диагональной клавиши — по случаю, в зависимости от углов предмета.

    Формул три, и каждая работает только в своём случае (не заменяя остальные):

    Наклон предмета — это ``RX`` (именно по нему интерфейс предупреждает о наклоне).

    1. **Наклона нет** (``RX = 0``) — диагональ 45° в плоскости экрана ``Y/Z``:
       ``ΔY = ay·(шаг/√2)``, ``ΔZ = ax·(шаг/√2)``, ``ΔX = 0``. ``Num 9`` уводит
       вправо (``−Y``) и вверх (``+Z``) на 45°; ``RZ`` и ``RY`` здесь не участвуют.
    2. **Наклонён только ``RX``** (``RX ≠ 0``, ``RY = 0``) — поворот в плоскости
       ``Y/Z``, ``X`` не меняется (``k = шаг/√2``). У каждой пары клавиш своя
       тригонометрия — эталоны заказчика 1.8.1:

       ```
       Num 9 и Num 1 (ax·ay = −1):   ΔY = ay · k · sin RX,   ΔZ = ax · k · cos RX
       Num 7 и Num 3 (ax·ay = +1):   ΔY = ay · k · cos RX,   ΔZ = ax · k · sin RX
       ```

    3. **Наклонены оба угла** (``RX ≠ 0`` и ``RY ≠ 0``) — для пары ``Num 9/1`` формула
       1.6.2 с ``L = шаг``; у пары ``Num 7/3`` остаётся формула случая 2 (``RY`` в неё
       не входит, ``X`` не меняется, длина ``шаг/√2``) — так задал заказчик:

       ```
       Num 9 и Num 1:  ΔX = ax · L · sin RY
                       ΔY = ay · L · sin RX · cos RY
                       ΔZ = ax · L · cos RX · cos RY          L = шаг

       Num 7 и Num 3:  ΔX = 0
                       ΔY = ay · (шаг/√2) · cos RX
                       ΔZ = ax · (шаг/√2) · sin RX
       ```

    ``ax = ±1`` — клавиша «вперёд/назад» (она же «вверх/вниз»), ``ay = ±1`` —
    «влево/вправо». Режим высоты (``Alt``) считается отдельно, см. ``_height_step``.
    """
    ax, ay = direction.axes
    if pose.rx == 0.0:
        return _flat_diagonal(ax, ay)
    # Пара Num 7/3 и при RY ≠ 0 считается по формуле плоскости Y/Z (эталон 1.8.2):
    # в формуле заказчика для этой пары RY не участвует.
    if pose.ry == 0.0 or ax * ay > 0:
        step = _rx_diagonal(ax, ay, pose.rx)
    else:
        step = _rx_ry_diagonal(ax, ay, pose.rx, pose.ry)
    # RZ поворачивает готовый шаг вокруг мировой оси Z — так выглядят формулы
    # заказчика для трёх углов (ADR-0027). Без наклона (RX = 0) RZ не участвует.
    return _rotate_z(step, pose.rz)


def _rotate_z(vector: tuple[float, float, float], degrees: float) -> tuple[float, float, float]:
    """Повернуть шаг вокруг мировой оси ``Z`` на ``RZ``.

    В формулах заказчика это множители ``cos RZ``/``sin RZ`` в ``X`` и ``Y``:

    ```
    Num 9/1: ΔX = ax·L·(sin RY·cos RZ + sin RX·cos RY·sin RZ)
             ΔY = ax·L·sin RY·sin RZ + ay·L·sin RX·cos RY·cos RZ
             ΔZ = ax·L·cos RX·cos RY

    Num 7/3: ΔX = ay·L·sin RZ·cos RX
             ΔY = −ay·L·cos RZ·cos RX
             ΔZ = ax·L·sin RX
    ```

    При ``RZ = 0`` вектор не меняется, поэтому все прежние эталоны с ``RZ = 0``
    остаются в силе.
    """
    if degrees == 0.0:
        return vector
    angle = math.radians(degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    x, y, z = vector
    return round(x * cos_a - y * sin_a, 12), round(x * sin_a + y * cos_a, 12), z


def _flat_diagonal(ax: int, ay: int) -> tuple[float, float, float]:
    """Случай 1 (``RX = 0``): диагональ 45° в плоскости экрана ``Y/Z``.

    ```Delta
    ΔX = 0,   ΔY = ay · (шаг/√2),   ΔZ = ax · (шаг/√2)
    ```

    Вправо на экране — это ``−Y``, вверх — ``+Z``, поэтому ``Num 9`` (``ax = +1``,
    ``ay = −1``) уводит вправо и вверх ровно на 45°. ``X`` (глубина) не меняется,
    длина шага — ``шаг``. ``RZ`` в эту формулу не входит.

    Эталон заказчика: ``RZ = RY = RX = 0``, шаг 3.0, `Num 9` из
    ``(−1849.342, 416.528, 129.816)`` → ``(−1849.342, 414.407, 131.937)``.
    """
    arm = 1.0 / math.hypot(ax, ay)
    return 0.0, round(ay * arm, 12), round(ax * arm, 12)


def _rx_diagonal(ax: int, ay: int, rx: float) -> tuple[float, float, float]:
    """Случай 2 (``RX ≠ 0``, ``RY = 0``): поворот в плоскости ``Y/Z`` — по паре клавиш.

    Пары заданы заказчиком, ``k = шаг/√2``, ``ΔX = 0``:

    ```Delta
    Num 9 и Num 1 (ax·ay = −1):   ΔY = ay · k · sin RX,   ΔZ = ax · k · cos RX
    Num 7 и Num 3 (ax·ay = +1):   ΔY = ay · k · cos RX,   ΔZ = ax · k · sin RX
    ```

    Угол поворота у пар разный: при ``RX = 76°`` и шаге 3 ``Num 9`` уходит вправо на
    2.058 и вверх на 0.513, а ``Num 3`` — вправо на 0.513 и вниз на 2.058. Длина шага
    у обеих пар одна: ``k``.

    Эталоны: ``RX = 37°``, шаг 2.0, ``Num 9`` → ``ΔY = −0.851``, ``ΔZ = +1.129``;
    ``RX = 76°``, шаг 3.0, ``Num 3`` → ``ΔY = −0.513``, ``ΔZ = −2.058``.
    """
    arm = 1.0 / math.hypot(ax, ay)
    angle = math.radians(rx)
    if ax * ay < 0:  # правая пара: Num 9 и Num 1
        dy, dz = math.sin(angle), math.cos(angle)
    else:  # левая пара: Num 7 и Num 3
        dy, dz = math.cos(angle), math.sin(angle)
    return 0.0, round(ay * arm * dy, 12), round(ax * arm * dz, 12)


def _rx_ry_diagonal(ax: int, ay: int, rx: float, ry: float) -> tuple[float, float, float]:
    """Случай 3 (``RX ≠ 0`` и ``RY ≠ 0``): поворот ``Rx(RX) · Ry(RY)`` — формула 1.6.2.

    ```Delta
    ΔX = ax · L · sin RY
    ΔY = ay · L · sin RX · cos RY
    ΔZ = ax · L · cos RX · cos RY          L = шаг
    ```

    Так считаются только клавиши пары ``Num 9/1``: у пары ``Num 7/3`` при ``RY ≠ 0``
    остаётся формула плоскости ``Y/Z`` (см. ``_diagonal``).

    Эталон заказчика: ``RX = 55°``, ``RY = 17°``, шаг 3.0 →
    ``(+0.877, −2.350, +1.646)``; второй — ``RX = 41.5°``, ``RY = 22.3°`` →
    ``(+1.138, −1.839, +2.079)``.
    """
    tx = math.radians(rx)
    ty = math.radians(ry)
    cos_ty = math.cos(ty)
    return (
        round(ax * math.sin(ty), 12),
        round(ay * math.sin(tx) * cos_ty, 12),
        round(ax * math.cos(tx) * cos_ty, 12),
    )


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
# Куда ведёт диагональная клавиша: ``Rx(RX) · Ry(RY)`` над локальной «вверх»-осью.

ALT_TITLES: Final[dict[Direction, str]] = {
    Direction.FORWARD: "вверх",
    Direction.BACK: "вниз",
}
# Что делают ``Num 8`` и ``Num 2`` при включённом режиме высоты.


def alt_hint() -> str:
    """Подсказка режима высоты: что делают клавиши при нажатом ``Alt``."""
    return "8 \u2191 вверх · 2 \u2193 вниз (ось Z, поворот RY)"


def changed_fields(before: Pose, after: Pose, *, tolerance: float = TOLERANCE) -> tuple[Field, ...]:
    """Поля, которые действительно отличаются (в порядке панели)."""
    return tuple(
        field for field in PANEL_ORDER if abs(after.value(field) - before.value(field)) > tolerance
    )
