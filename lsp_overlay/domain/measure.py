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
SMALL_DIMENSION = 0.02
SIGNIFICANT_DISTANCE = 0.5
ROTATION_TOLERANCE = 0.5
ZERO_ANGLES: Vec3 = (0.0, 0.0, 0.0)


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
    angles_a: Vec3 = ZERO_ANGLES
    angles_b: Vec3 = ZERO_ANGLES

    @classmethod
    def between(cls, first: Pose, second: Pose) -> Span:
        """Строит замер по двум позам: позиции и углы пропа в каждой точке."""
        return cls(
            point_a=first.position,
            point_b=second.position,
            angles_a=first.angles,
            angles_b=second.angles,
        )

    @property
    def angles(self) -> Vec3:
        """Углы пропа, по которым считаются длина и ширина — углы точки ``A``."""
        return self.angles_a

    @property
    def prop_was_rotated(self) -> bool:
        """Проп поворачивали между замерами — оси отсчёта могли измениться."""
        return any(
            abs(first - second) > ROTATION_TOLERANCE
            for first, second in zip(self.angles_a, self.angles_b, strict=True)
        )

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

    def dimension_value(self, dimension: Dimension, angles: Vec3 | None = None) -> float:
        """Длина предмета по одному габариту.

        ``Длина`` и ``Ширина`` берутся вдоль локальных осей предмета (поэтому поворот
        пропа не мешает), ``Толщина`` — по вертикали мира: её меряют, поставив проп
        на верхнюю и на нижнюю грань плиты.
        """
        if dimension is Dimension.THICKNESS:
            return self.vertical
        index = 1 if dimension is Dimension.LENGTH else 0
        reference = self.angles if angles is None else angles
        return abs(self.local_offsets(reference)[index])

    def projections(self) -> dict[Dimension, float]:
        """Сколько выйдет по каждому габариту, если записать этот замер."""
        offsets = self.local_offsets(self.angles)
        return {
            Dimension.LENGTH: abs(offsets[1]),
            Dimension.WIDTH: abs(offsets[0]),
            Dimension.THICKNESS: self.vertical,
        }

    def axis_hint(self, dimension: Dimension) -> str | None:
        """Предупреждение, если замер не похож на выбранный габарит.

        Две точки на разных краях стены легко измерить не по той оси: тогда проекция
        на нужный габарит почти нулевая, хотя между точками метры. Молча записывать
        такой «ноль» нельзя — из него потом считается стык.
        """
        if self.is_degenerate:
            return None
        if self.prop_was_rotated:
            return (
                "Проп поворачивали между замерами: длина и ширина считаются по углам "
                "точки A. Поставьте обе точки при одном угле пропа."
            )
        value = self.dimension_value(dimension)
        if value >= SMALL_DIMENSION or self.distance < SIGNIFICANT_DISTANCE:
            return None
        projections = self.projections()
        line = " · ".join(
            f"{other.label.lower()} {projections[other]:.2f} м" for other in Dimension
        )
        return (
            f"Габарит «{dimension.label}»: {value:.3f} м, а между точками {self.distance:.2f} м — "
            f"замер идёт почти вдоль другой оси. По этой линии: {line}. "
            "Проверьте, какой габарит выбран, и угол пропа (RZ)."
        )

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
