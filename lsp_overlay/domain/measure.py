"""Измерения: расстояние между двумя замерами и шаг для стыковки объектов."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from lsp_overlay.domain.catalog import Dimension
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import Vec3, inverse_transform, rotation_matrix
from lsp_overlay.domain.pose import Pose

FULL_TURN = 360.0
MIN_MEANINGFUL_SPAN = 0.001


class MeasureSlot(StrEnum):
    """Ячейка рулетки: первый и второй замер."""

    FIRST = "a"
    SECOND = "b"

    @property
    def label(self) -> str:
        """Подпись точки для интерфейса."""
        return "A" if self is MeasureSlot.FIRST else "B"


@dataclass(frozen=True, slots=True)
class Span:
    """Расстояние между двумя точками замера.

    Замеры делаются положением пропа: поставили у одного края объекта, запомнили,
    переставили к другому краю — получили его длину.
    """

    point_a: Vec3
    point_b: Vec3

    @classmethod
    def between(cls, first: Pose, second: Pose) -> Span:
        """Строит замер по двум позам (углы не важны, берётся позиция)."""
        return cls(point_a=first.position, point_b=second.position)

    @property
    def delta(self) -> Vec3:
        """Разница координат ``B - A`` по осям."""
        return (
            self.point_b[0] - self.point_a[0],
            self.point_b[1] - self.point_a[1],
            self.point_b[2] - self.point_a[2],
        )

    @property
    def distance(self) -> float:
        """Длина по прямой между точками."""
        dx, dy, dz = self.delta
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @property
    def planar(self) -> float:
        """Длина в плане (без высоты) — по ней обычно и стыкуют объекты."""
        dx, dy, _ = self.delta
        return math.sqrt(dx * dx + dy * dy)

    @property
    def vertical(self) -> float:
        """Перепад высоты (неотрицательный)."""
        return abs(self.delta[2])

    @property
    def heading(self) -> float:
        """Направление A → B по компасу: ``0°`` — север (``+Y``), по часовой."""
        dx, dy, _ = self.delta
        return math.degrees(math.atan2(dx, dy)) % FULL_TURN

    @property
    def is_degenerate(self) -> bool:
        """Точки совпали — измерять нечего."""
        return self.distance < MIN_MEANINGFUL_SPAN

    def axis_span(self, index: int) -> float:
        """Длина проекции на ось: ``0`` — X, ``1`` — Y, ``2`` — Z."""
        if index not in (0, 1, 2):
            raise ValidationError("ось измерения — только 0, 1 или 2")
        return abs(self.delta[index])

    def local_offsets(self, angles: Vec3) -> Vec3:
        """Смещение в осях предмета: ``X`` вправо, ``Y`` вперёд, ``Z`` вверх."""
        return inverse_transform(self.delta, rotation_matrix(*angles))

    def dimension_value(self, dimension: Dimension, angles: Vec3) -> float:
        """Длина предмета по одному габариту.

        ``Длина`` и ``Ширина`` берутся вдоль локальных осей предмета (поэтому поворот
        пропа не мешает), ``Высота`` — по вертикали мира.
        """
        if dimension is Dimension.HEIGHT:
            return self.vertical
        index = 1 if dimension is Dimension.LENGTH else 0
        return abs(self.local_offsets(angles)[index])

    def length_for_step(self) -> float:
        """Шаг для стыковки вплотную: длина в плане, а если она нулевая — по прямой."""
        planar = self.planar
        return planar if planar >= MIN_MEANINGFUL_SPAN else self.distance


class MeasureTape:
    """Две ячейки рулетки; хранит позы, из которых считается :class:`Span`."""

    def __init__(self) -> None:
        self._points: dict[MeasureSlot, Pose] = {}

    @property
    def points(self) -> dict[MeasureSlot, Pose]:
        """Текущие замеры (копия, чтобы внешний код не менял состояние)."""
        return dict(self._points)

    def point(self, slot: MeasureSlot) -> Pose | None:
        """Поза в ячейке или ``None``, если замер не делался."""
        return self._points.get(slot)

    def remember(self, slot: MeasureSlot, pose: Pose) -> None:
        """Кладёт позу в ячейку."""
        self._points[slot] = pose

    def span(self) -> Span | None:
        """Замер, если заполнены обе ячейки."""
        first = self._points.get(MeasureSlot.FIRST)
        second = self._points.get(MeasureSlot.SECOND)
        if first is None or second is None:
            return None
        return Span.between(first, second)

    def clear(self) -> None:
        """Сбрасывает обе ячейки."""
        self._points.clear()
