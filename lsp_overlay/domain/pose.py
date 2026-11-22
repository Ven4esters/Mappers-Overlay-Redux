"""Поза пропа: координаты и углы. Неизменяемая структура."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from lsp_overlay.domain.geometry import Vec3, wrap_angle


class Axis(StrEnum):
    """Ось вращения."""

    PITCH = "rx"
    ROLL = "ry"
    YAW = "rz"


@dataclass(frozen=True, slots=True)
class Pose:
    """Положение и ориентация предмета в мировых координатах."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0

    @property
    def position(self) -> Vec3:
        """Мировая позиция."""
        return (self.x, self.y, self.z)

    @property
    def angles(self) -> Vec3:
        """Углы ``(RX, RY, RZ)`` в градусах."""
        return (self.rx, self.ry, self.rz)

    def translated(self, delta: Vec3) -> Pose:
        """Возвращает новую позу, сдвинутую на мировой вектор."""
        return replace(self, x=self.x + delta[0], y=self.y + delta[1], z=self.z + delta[2])

    def turned(self, axis: Axis, degrees: float) -> Pose:
        """Поворачивает предмет вокруг своей оси на ``degrees`` с нормализацией угла."""
        current = getattr(self, axis.value)
        return replace(self, **{axis.value: wrap_angle(current + degrees)})

    def with_angle(self, axis: Axis, degrees: float) -> Pose:
        """Задаёт абсолютный угол по оси (нормализуется к ``[-180, 180)``)."""
        return replace(self, **{axis.value: wrap_angle(degrees)})

    def rounded(self, length_decimals: int, angle_decimals: int = 2) -> Pose:
        """Округляет значения до точности, которой пользуется игра."""
        return Pose(
            x=round(self.x, length_decimals) + 0.0,
            y=round(self.y, length_decimals) + 0.0,
            z=round(self.z, length_decimals) + 0.0,
            rx=round(self.rx, angle_decimals) + 0.0,
            ry=round(self.ry, angle_decimals) + 0.0,
            rz=round(self.rz, angle_decimals) + 0.0,
        )
