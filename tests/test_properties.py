"""Свойства формул сдвига: эталоны ловят числа, а эти тесты — правила.

Эталонный тест говорит «при таких углах шаг равен 0.5209». Он не заметит, если формула
начнёт зависеть от ``RZ`` там, где не должна, или если «назад» перестанет быть
противоположностью «вперёд»: числа подставят другие, а правило останется сломанным.

Здесь проверяются инварианты, которые обязаны выполняться при любых углах и шагах:

* длина шага равна шагу (винт: у диагонали — ``шаг`` или ``шаг/√2`` по случаю);
* пара «вперёд/назад» и «влево/вправо» даёт противоположные векторы;
* ``RZ`` поворачивает шаг, не меняя его длины и ``Z``;
* прямой шаг не меняет ``Z``, а высота — ``Y``.

Точность — по округлению координат (``COORD_DECIMALS``): формула считает в ``float``,
а координаты пишутся с тремя знаками, поэтому допуск 2 мм.
"""

from __future__ import annotations

import math
from dataclasses import replace

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from map_overlay.domain.directions import Direction
from map_overlay.domain.movement import changed_fields, shifted
from map_overlay.domain.pose import Pose

EXAMPLES = 1000
TOLERANCE = 2e-3
# Допуск по расстоянию: координаты округляются до миллиметра, ошибка на ось — 0.5 мм.

CARDINALS = (Direction.FORWARD, Direction.BACK, Direction.LEFT, Direction.RIGHT)
DIAGONALS = (
    Direction.FORWARD_LEFT,
    Direction.FORWARD_RIGHT,
    Direction.BACK_LEFT,
    Direction.BACK_RIGHT,
)
OPPOSITE = {
    Direction.FORWARD: Direction.BACK,
    Direction.BACK: Direction.FORWARD,
    Direction.LEFT: Direction.RIGHT,
    Direction.RIGHT: Direction.LEFT,
    Direction.FORWARD_LEFT: Direction.BACK_RIGHT,
    Direction.FORWARD_RIGHT: Direction.BACK_LEFT,
    Direction.BACK_LEFT: Direction.FORWARD_RIGHT,
    Direction.BACK_RIGHT: Direction.FORWARD_LEFT,
}

angles = st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False)
steps = st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False)
cardinal = st.sampled_from(CARDINALS)
diagonal = st.sampled_from(DIAGONALS)
any_direction = st.sampled_from(tuple(Direction))

RULE = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def _delta(
    pose: Pose, direction: Direction, step: float, *, tilt: bool = False, straight: bool = False
) -> tuple[float, float, float]:
    """Вектор шага от нулевой позы: так погрешность округления не зависит от координат."""
    start = Pose(x=0.0, y=0.0, z=0.0, rx=pose.rx, ry=pose.ry, rz=pose.rz)
    moved = shifted(start, direction, step, tilt=tilt, straight=straight)
    return (moved.x - start.x, moved.y - start.y, moved.z - start.z)


def _length(*vector: float) -> float:
    return math.hypot(*vector)


@RULE
@given(direction=cardinal, step=steps, rz=angles)
def test_direct_step_has_the_step_length(direction: Direction, step: float, rz: float) -> None:
    """Прямой шаг: длина в горизонтали равна шагу, высота не меняется."""
    dz, dy, dzz = _delta(Pose(rx=0.0, ry=0.0, rz=rz), direction, step)
    assert dzz == 0.0
    assert abs(_length(dz, dy) - step) <= TOLERANCE


@RULE
@given(direction=cardinal, step=steps, rz=angles)
def test_opposite_keys_give_opposite_vectors(direction: Direction, step: float, rz: float) -> None:
    """«Вперёд» и «назад» — один и тот же шаг в разные стороны."""
    pose = Pose(rx=0.0, ry=0.0, rz=rz)
    forward = _delta(pose, direction, step)
    backward = _delta(pose, OPPOSITE[direction], step)
    for plus, minus in zip(forward, backward, strict=True):
        assert abs(plus + minus) <= TOLERANCE


@RULE
@given(direction=cardinal, step=steps, rz=angles)
def test_rz_rotates_without_changing_the_length(
    direction: Direction, step: float, rz: float
) -> None:
    """``RZ`` поворачивает шаг вокруг вертикали: длина и ``Z`` те же, что у нуля."""
    straight = _delta(Pose(rx=0.0, ry=0.0, rz=0.0), direction, step)
    rotated = _delta(Pose(rx=0.0, ry=0.0, rz=rz), direction, step)
    assert abs(_length(*straight) - _length(*rotated)) <= TOLERANCE
    assert abs(straight[2] - rotated[2]) <= TOLERANCE


@RULE
@given(direction=st.sampled_from((Direction.FORWARD, Direction.BACK)), step=steps, ry=angles)
def test_height_step_goes_by_the_local_z_axis(direction: Direction, step: float, ry: float) -> None:
    """Режим высоты: шаг в плоскости ``X/Z``, длина — шаг, ``Y`` не меняется."""
    dx, dy, dz = _delta(Pose(rx=30.0, ry=ry, rz=15.0), direction, step, tilt=True)
    assert dy == 0.0
    assert abs(_length(dx, dz) - step) <= TOLERANCE


@RULE
@given(direction=st.sampled_from((Direction.FORWARD, Direction.BACK)), step=steps, ry=angles)
def test_straight_height_step_ignores_the_tilt(
    direction: Direction, step: float, ry: float
) -> None:
    """«Прямой шаг» в высоте: строго по мировой ``Z``, вбок не уводит."""
    dx, dy, dz = _delta(Pose(rx=45.0, ry=ry, rz=15.0), direction, step, tilt=True, straight=True)
    assert (dx, dy) == (0.0, 0.0)
    assert abs(abs(dz) - step) <= TOLERANCE


@RULE
@given(direction=any_direction, step=steps, rx=angles, ry=angles, rz=angles)
def test_every_step_is_the_step_length_or_its_diagonal_part(
    direction: Direction, step: float, rx: float, ry: float, rz: float
) -> None:
    """Любой шаг не длиннее шага: диагональ идёт на ``шаг/√2``, а не «на сколько вышло».

    Формула, которая потеряет нормировку (например, забудет ``/√2`` или умножит на
    ``cos`` дважды), даст шаг короче или длиннее — и это видно без эталонных чисел.
    """
    vector = _delta(Pose(rx=rx, ry=ry, rz=rz), direction, step)
    length = _length(*vector)
    assert length <= step + TOLERANCE
    assert length >= step / math.sqrt(2) - TOLERANCE


@RULE
@given(direction=diagonal, step=steps, rz=angles)
def test_flat_diagonal_turns_only_on_rz(direction: Direction, step: float, rz: float) -> None:
    """Без наклона диагональ идёт в плоскости ``Y/Z``: ``X`` не меняется."""
    dx, dy, dz = _delta(Pose(rx=0.0, ry=0.0, rz=rz), direction, step)
    assert dx == 0.0
    assert abs(_length(dx, dy, dz) - step) <= TOLERANCE


@RULE
@given(direction=diagonal, step=steps, rx=st.floats(min_value=1.0, max_value=179.0))
def test_diagonal_with_one_angle_stays_on_the_diagonal(
    direction: Direction, step: float, rx: float
) -> None:
    """Один ``RX``: шаг в плоскости ``Y/Z`` длиной ``шаг/√2`` — половина стороны квадрата."""
    dx, dy, dz = _delta(Pose(rx=rx, ry=0.0, rz=0.0), direction, step)
    assert dx == 0.0
    assert abs(_length(dy, dz) - step / math.sqrt(2)) <= TOLERANCE


@RULE
@given(rx=angles, ry=angles, rz=angles, step=steps)
def test_changed_fields_do_not_depend_on_order(
    rx: float, ry: float, rz: float, step: float
) -> None:
    """«Что изменилось» — свойство пары поз, а не порядка аргументов."""
    start = Pose(x=1.0, y=2.0, z=3.0, rx=rx, ry=ry, rz=rz)
    moved = shifted(start, Direction.FORWARD, step)
    assert changed_fields(start, moved) == changed_fields(moved, start)


@RULE
@given(step=steps, rz=angles)
def test_step_never_moves_by_zero_or_more_than_the_step(step: float, rz: float) -> None:
    """Ненулевой шаг не может оставить предмет на месте или увести его дальше шага."""
    start = Pose(x=0.0, y=0.0, z=0.0, rx=0.0, ry=0.0, rz=rz)
    moved = shifted(start, Direction.FORWARD, step)
    assert moved != start
    assert replace(moved, rx=0.0, ry=0.0, rz=rz) == moved
    assert abs(moved.x - start.x) <= step + TOLERANCE
