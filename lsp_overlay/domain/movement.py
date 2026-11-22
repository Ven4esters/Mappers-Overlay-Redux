"""Сдвиг и поворот пропа с учётом его собственных углов."""

from __future__ import annotations

import math
from enum import StrEnum

from lsp_overlay.domain.directions import DiagonalMode, Direction, is_diagonal, local_vector
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import add_scaled, normalize_diagonal, rotation_matrix, transform
from lsp_overlay.domain.pose import Axis, Pose

MIN_MOVE_ROTATION = -180.0
MAX_MOVE_ROTATION = 360.0


class MoveFrame(StrEnum):
    """В каких осях двигают стрелки.

    ``PROP`` — по осям самого предмета: `↑` уводит его «вперёд», вдоль длины, а `←`/`→` —
    ровно поперёк, как бы он ни был повёрнут. Поэтому при ``RZ = 70°`` боковой шаг меняет
    `X` и `Y` одновременно, и предмет едет ровно, не заваливаясь в мировую ось. ``WORLD`` —
    всегда по сторонам света: `↑` это `+Y` (север), `→` это `+X` (восток), угол предмета
    не учитывается (``rotation`` подменяет его поправкой на поворот камеры).
    """

    WORLD = "world"
    PROP = "prop"

    @property
    def label(self) -> str:
        """Название для интерфейса."""
        return {
            MoveFrame.PROP: "Предмет: поперёк и вдоль детали (X и Y вместе)",
            MoveFrame.WORLD: "Мир: ↑ север (+Y), → восток (+X) — угол не важен",
        }[self]


def _validate_step(step: float) -> None:
    if not math.isfinite(step):
        raise ValidationError("шаг должен быть конечным числом")
    if step <= 0.0:
        raise ValidationError("шаг должен быть больше нуля")


def _validate_angle(degrees: float) -> None:
    if not math.isfinite(degrees):
        raise ValidationError("угол должен быть конечным числом")


def _local_offset(
    direction: Direction,
    step: float,
    diagonal_mode: DiagonalMode,
) -> tuple[float, float, float]:
    vector = local_vector(direction)
    if diagonal_mode is DiagonalMode.SAME_DISTANCE and is_diagonal(direction):
        vector = normalize_diagonal(vector)
    return add_scaled((0.0, 0.0, 0.0), vector, step)


def move(
    pose: Pose,
    direction: Direction,
    step: float,
    *,
    diagonal_mode: DiagonalMode = DiagonalMode.SAME_DISTANCE,
    use_tilt: bool = True,
    frame: MoveFrame = MoveFrame.PROP,
    rotation: float = 0.0,
) -> Pose:
    """Сдвигает проп на ``step`` метров в направлении ``direction``.

    Сдвиг считается в локальных осях предмета и переводится в мировые координаты,
    поэтому при ``RZ = 90°`` и ``frame=MoveFrame.PROP`` кнопка «вперёд» уводит проп на запад,
    вдоль его собственной оси, а «влево» — на юг: `X` и `Y` меняются вместе, предмет едет
    ровно поперёк своей стороны. При ``frame=MoveFrame.WORLD`` поворот пропа не учитывается:
    `↑` всегда север (или ``rotation`` вместо него — поправка на поворот камеры).
    При ``use_tilt=False`` учитывается только поворот вокруг вертикали
    (``RZ``), наклоны игнорируются — движение остаётся в плоскости пола.
    """
    _validate_step(step)
    local = _local_offset(direction, step, diagonal_mode)
    if frame is MoveFrame.WORLD:
        # поворот осей — поправка на камеру: камера смотрит не строго на север,
        # и «вверх» на экране оказывается под углом к мировой оси
        matrix = rotation_matrix(0.0, 0.0, rotation)
    elif use_tilt:
        matrix = rotation_matrix(pose.rx, pose.ry, pose.rz)
    else:
        matrix = rotation_matrix(0.0, 0.0, pose.rz)
    return pose.translated(transform(local, matrix))


def rotate(pose: Pose, axis: Axis, degrees: float) -> Pose:
    """Поворачивает проп на ``degrees`` вокруг собственной оси ``axis``."""
    _validate_angle(degrees)
    return pose.turned(axis, degrees)
