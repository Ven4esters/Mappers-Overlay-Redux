"""Поза предмета: три координаты и три угла."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from map_overlay.domain.fields import Field

POSITION_FIELDS: tuple[Field, ...] = (Field.X, Field.Y, Field.Z)


@dataclass(frozen=True, slots=True)
class Pose:
    """Неизменяемая поза предмета в мировых координатах.

    Углы хранятся в градусах, координаты — в метрах, как их отдаёт панель LSP.
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0

    def value(self, field: Field) -> float:
        """Значение поля по его перечислению."""
        return cast("float", getattr(self, field.value))

    def with_value(self, field: Field, value: float) -> Pose:
        """Копия позы с заменённым одним полем."""
        return replace(self, **{field.value: value})

    def values(self) -> dict[Field, float]:
        """Все значения в порядке панели."""
        return {field: self.value(field) for field in Field}

    @property
    def has_tilt(self) -> bool:
        """Есть ли наклон ``RX``/``RY``: ``RX`` учитывается по Alt, ``RY`` — пока нет."""
        return any(abs(self.value(field)) > 1e-9 for field in (Field.RX, Field.RY))
