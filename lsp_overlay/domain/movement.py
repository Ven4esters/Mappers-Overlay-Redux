"""Сдвиг и поворот пропа с учётом его собственных углов."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from lsp_overlay.domain.directions import DiagonalMode, Direction, is_diagonal, local_vector
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.geometry import normalize_diagonal, rotation_matrix, transform
from lsp_overlay.domain.pose import Axis, Pose

MIN_MOVE_ROTATION = -180.0
MAX_MOVE_ROTATION = 360.0


class MoveSpace(StrEnum):
    """В каких осях двигают стрелки — как в первой версии приложения.

    ``OBJECT`` (по умолчанию) — по углу самого предмета ``RZ``, строго параллельно полу:
    `↑` вдоль детали, `←`/`→` ровно поперёк неё. При ``RZ = 70°`` боковой шаг меняет `X` и
    `Y` одновременно (`ΔX = −step·cos RZ`, `ΔY = −step·sin RZ`), а `Z` не трогается.
    ``ANCHOR`` — по базовому углу комнаты: направление задаёт запомненный якорь, поэтому
    поворот предмета после этого шаг уже не меняет. ``WORLD`` — по сторонам света:
    `↑` это `+Y` (север), `→` это `+X` (восток); там же работает поправка на камеру.
    """

    OBJECT = "object"
    ANCHOR = "anchor"
    WORLD = "world"

    @property
    def label(self) -> str:
        """Название для интерфейса."""
        return {
            MoveSpace.OBJECT: "Предмет: по его углу RZ (как в v1)",
            MoveSpace.ANCHOR: "Якорь комнаты: по базовому углу",
            MoveSpace.WORLD: "Мир: ↑ север (+Y), → восток (+X)",
        }[self]


@dataclass(frozen=True, slots=True)
class InvertSigns:
    """Поправки направлений: на некоторых сборках оси сервера зеркалят."""

    right: bool = False
    forward: bool = False
    up: bool = False

    @property
    def any(self) -> bool:
        """Включена ли хоть одна поправка."""
        return self.right or self.forward or self.up

    def signs(self) -> tuple[float, float, float]:
        """Множители для локальных «вправо», «вперёд», «вверх»."""
        return (
            -1.0 if self.right else 1.0,
            -1.0 if self.forward else 1.0,
            -1.0 if self.up else 1.0,
        )


def planar_step(right: float, forward: float, angle: float) -> tuple[float, float]:
    """Переводит локальные (вправо, вперёд) в мировые ΔX/ΔY.

    Формула дословно та же, что в первой версии (``rotate_2d_gta``): ``+X`` — восток,
    ``+Y`` — север, ``RZ`` — против часовой, ``RZ = 0°`` — «вперёд» на север.
    """
    rad = math.radians(angle)
    cos_z = math.cos(rad)
    sin_z = math.sin(rad)
    return (right * cos_z - forward * sin_z, right * sin_z + forward * cos_z)


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
    invert: InvertSigns,
) -> tuple[float, float, float]:
    """Смещение в локальных осях предмета с поправками направлений."""
    vector = local_vector(direction)
    if diagonal_mode is DiagonalMode.SAME_DISTANCE and is_diagonal(direction):
        vector = normalize_diagonal(vector)
    signs = invert.signs()
    return (vector[0] * step * signs[0], vector[1] * step * signs[1], vector[2] * step * signs[2])


def move(
    pose: Pose,
    direction: Direction,
    step: float,
    *,
    diagonal_mode: DiagonalMode = DiagonalMode.SAME_DISTANCE,
    use_tilt: bool = False,
    frame: MoveSpace = MoveSpace.OBJECT,
    rotation: float = 0.0,
    anchor: float = 0.0,
    invert: InvertSigns = InvertSigns(),
) -> Pose:
    """Сдвигает проп на ``step`` метров в направлении ``direction``.

    Локальное смещение переводится в мировые ``ΔX``/``ΔY`` поворотом на ``RZ`` предмета —
    так же, как это делала первая версия. При ``RZ = 70°`` нажатие «влево» даёт
    ``ΔX = −0.342``, ``ΔY = −0.940`` на метр: предмет едет ровно поперёк своей стороны.
    ``Z`` при этом не меняется.

    * ``use_tilt=True`` — единственный случай, когда в матрицу попадают ``RX``/``RY``
      (движение по плоскости наклонённой детали). По умолчанию, как в v1, наклоны
      игнорируются, и шаг остаётся горизонтальным.
    * ``frame=MoveSpace.ANCHOR`` поворачивает шаг на ``anchor`` — базовый угол комнаты.
    * ``frame=MoveSpace.WORLD`` игнорирует предмет: `↑` всегда север, а ``rotation``
      подменяет стороны света поправкой на поворот камеры.
    * ``invert`` зеркалит отдельные направления для сборок с перевёрнутыми осями.
    """
    _validate_step(step)
    right, forward, up = _local_offset(direction, step, diagonal_mode, invert)
    if frame is MoveSpace.WORLD:
        dx, dy = planar_step(right, forward, rotation)
        dz = up
    elif frame is MoveSpace.ANCHOR or not use_tilt:
        # угол берём только вокруг вертикали: шаг остаётся параллельным полу
        yaw = anchor if frame is MoveSpace.ANCHOR else pose.rz
        dx, dy = planar_step(right, forward, yaw)
        dz = up
    else:
        dx, dy, dz = transform((right, forward, up), rotation_matrix(pose.rx, pose.ry, pose.rz))
    return pose.translated((dx, dy, dz))


def rotate(pose: Pose, axis: Axis, degrees: float) -> Pose:
    """Поворачивает проп на ``degrees`` вокруг собственной оси ``axis``."""
    _validate_angle(degrees)
    return pose.turned(axis, degrees)
