"""Сдвиг и поворот пропа с учётом его собственных углов."""

from __future__ import annotations

import math

from lsp_overlay.domain.directions import DiagonalMode, Direction, is_diagonal, local_vector
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import add_scaled, normalize_diagonal, rotation_matrix, transform
from lsp_overlay.domain.pose import Axis, Pose


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
) -> Pose:
    """Сдвигает проп на ``step`` метров в направлении ``direction``.

    Сдвиг считается в локальных осях предмета и переводится в мировые координаты,
    поэтому при ``RZ = 90°`` кнопка «вперёд» уводит проп на запад, вдоль его
    собственной оси, а не в произвольном направлении. При ``use_tilt=False``
    учитывается только поворот вокруг вертикали (``RZ``), наклоны игнорируются —
    движение остаётся в плоскости пола.
    """
    _validate_step(step)
    local = _local_offset(direction, step, diagonal_mode)
    matrix = (
        rotation_matrix(pose.rx, pose.ry, pose.rz)
        if use_tilt
        else rotation_matrix(0.0, 0.0, pose.rz)
    )
    return pose.translated(transform(local, matrix))


def rotate(pose: Pose, axis: Axis, degrees: float) -> Pose:
    """Поворачивает проп на ``degrees`` вокруг собственной оси ``axis``."""
    _validate_angle(degrees)
    return pose.turned(axis, degrees)
