"""Стык двух предметов: буква Г (торец к торцу) и буква Т (торец в бок).

Стык считается по осям объекта ``A``: объект ``A`` стоит там, где сейчас проп, объект ``B``
приставляется к нему так, чтобы грани сошлись точно — без щели и без наложения.
Опорная точка — угол ``A`` на выбранной стороне: и торец ``B``, и его боковая грань
проходят через этот угол, поэтому координаты получаются точными, а не «на глаз».

Угол ``A`` учитывается целиком (``RX``, ``RY``, ``RZ``): на карте предмет часто повёрнут
не по осям мира — его ставят ровно по месту, и стык должен идти вдоль его собственных
граней, а не вдоль севера.

Локальные оси ``A``: ``X`` — поперёк (поперечный габарит), ``Y`` — вдоль длины,
``Z`` вверх. Угол отсчитывается против часовой стрелки, как и ``RZ``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from lsp_overlay.domain.catalog import Dimension, ObjectSpec
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import rotation_matrix, transform
from lsp_overlay.domain.pose import Axis, Pose

CORNER_ANGLE = 90.0
MITRE_ANGLE = 45.0
MIN_JOIN_ANGLE = 5.0
MAX_JOIN_ANGLE = 175.0
TEE_ANGLE = 90.0
ACROSS_EPSILON = 1e-9


class AcrossField(StrEnum):
    """Какой габарит считать поперечным размером при стыке.

    По умолчанию — толщина: детали сходятся тонкими гранями, и именно толщина задаёт,
    насколько вторая деталь отходит от оси первой. Ширина нужна для плоских плит,
    которые стыкуются всей плоскостью.
    """

    THICKNESS = "thickness"
    WIDTH = "width"

    @property
    def dimension(self) -> Dimension:
        """Габарит, из которого берётся поперечный размер."""
        return Dimension.THICKNESS if self is AcrossField.THICKNESS else Dimension.WIDTH

    @property
    def label(self) -> str:
        """Название для интерфейса."""
        return self.dimension.label


class JoinScheme(StrEnum):
    """Схема стыка."""

    CORNER = "corner"
    TEE = "tee"

    @property
    def label(self) -> str:
        """Название для интерфейса."""
        return {JoinScheme.CORNER: "Буква Г (торец к торцу)", JoinScheme.TEE: "Буква Т (в бок)"}[
            self
        ]


class JoinSide(StrEnum):
    """С какой стороны от ``A`` ставится ``B``."""

    LEFT = "left"
    RIGHT = "right"

    @property
    def label(self) -> str:
        """Название для интерфейса."""
        return {JoinSide.LEFT: "Влево", JoinSide.RIGHT: "Вправо"}[self]

    @property
    def turn(self) -> float:
        """Знак поворота в градусах ``RZ``: влево — против часовой стрелки."""
        return 1.0 if self is JoinSide.LEFT else -1.0


@dataclass(frozen=True, slots=True)
class JoinRequest:
    """Что и под каким углом приставляем."""

    scheme: JoinScheme = JoinScheme.CORNER
    angle: float = CORNER_ANGLE
    side: JoinSide = JoinSide.RIGHT
    across: AcrossField = AcrossField.THICKNESS

    def validated(self) -> JoinRequest:
        """Проверяет угол и приводит его к допустимому диапазону."""
        if self.scheme is JoinScheme.TEE:
            return JoinRequest(
                scheme=self.scheme, angle=TEE_ANGLE, side=self.side, across=self.across
            )
        if not math.isfinite(self.angle):
            raise ValidationError("угол стыка должен быть числом")
        if not MIN_JOIN_ANGLE <= self.angle <= MAX_JOIN_ANGLE:
            raise ValidationError(f"угол стыка — от {MIN_JOIN_ANGLE:g}° до {MAX_JOIN_ANGLE:g}°")
        return self


def across_of(spec: ObjectSpec, field: AcrossField = AcrossField.THICKNESS) -> float:
    """Поперечный размер предмета: он определяет, насколько глубоко деталь встаёт в стык."""
    return spec.dimension(field.dimension)


def _ensure_measurable(spec: ObjectSpec, field: AcrossField) -> None:
    if spec.length <= ACROSS_EPSILON:
        raise ValidationError(
            f"у предмета «{spec.name}» не измерена длина — без неё стык не посчитать"
        )
    across = across_of(spec, field)
    if across < -ACROSS_EPSILON:
        raise ValidationError(f"у предмета «{spec.name}» отрицательный поперечный размер")
    # Ноль допустим: плоская стена без толщины стыкуется торец в торец по своей плоскости.


def local_offset(
    first: ObjectSpec,
    second: ObjectSpec,
    request: JoinRequest,
) -> tuple[float, float]:
    """Смещение центра ``B`` в локальных осях ``A`` (поперёк, вдоль)."""
    request = request.validated()
    _ensure_measurable(first, request.across)
    _ensure_measurable(second, request.across)
    side = request.side.turn
    half_across_first = across_of(first, request.across) / 2.0
    half_across_second = across_of(second, request.across) / 2.0
    half_length_second = second.length / 2.0

    if request.scheme is JoinScheme.TEE:
        # B упирается торцом в бок A и растёт наружу; середина стыка — центр A
        contact_x = -side * half_across_first
        return contact_x - side * half_length_second, 0.0

    phi = math.radians(request.angle)
    # направление длины B и его внешней стороны в осях A
    u = (-side * math.sin(phi), math.cos(phi))
    v = (side * math.cos(phi), math.sin(phi))
    contact_x = -side * half_across_first
    contact_y = first.length / 2.0
    return (
        contact_x + half_length_second * u[0] - half_across_second * v[0],
        contact_y + half_length_second * u[1] - half_across_second * v[1],
    )


def join_pose(
    base: Pose,
    first: ObjectSpec,
    second: ObjectSpec,
    request: JoinRequest,
) -> Pose:
    """Поза ``B``, приставленного к ``A`` без щели и наложения."""
    request = request.validated()
    offset_x, offset_y = local_offset(first, second, request)
    # поворот берём целиком: RZ поворачивает стык в плане, RX/RY — наклон предмета
    offset = transform((offset_x, offset_y, 0.0), rotation_matrix(*base.angles))
    turned = base.turned(Axis.YAW, request.side.turn * request.angle)
    return Pose(
        x=base.x + offset[0],
        y=base.y + offset[1],
        z=base.z + offset[2],
        rx=turned.rx,
        ry=turned.ry,
        rz=turned.rz,
    )
