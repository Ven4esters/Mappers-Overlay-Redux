"""Поля панели LSP, с которыми работает оверлей."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Field(StrEnum):
    """Поле панели. Значение совпадает с именем атрибута позы."""

    X = "x"
    Y = "y"
    Z = "z"
    RX = "rx"
    RY = "ry"
    RZ = "rz"

    @property
    def label(self) -> str:
        """Подпись поля в интерфейсе и сообщениях."""
        return self.name

    @property
    def is_angle(self) -> bool:
        """Угол ли это (градусы, а не метры)."""
        return self in ANGLE_FIELDS


PANEL_ORDER: Final[tuple[Field, ...]] = (
    Field.X,
    Field.Y,
    Field.Z,
    Field.RX,
    Field.RY,
    Field.RZ,
)
"""Порядок полей в панели: по нему идёт обход при чтении и записи."""

ANGLE_FIELDS: Final[frozenset[Field]] = frozenset({Field.RX, Field.RY, Field.RZ})
