"""Точка экрана в физических пикселях."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    """Координаты курсора/клика. Хранятся в физических пикселях экрана."""

    x: int
    y: int

    def __str__(self) -> str:
        return f"{self.x}, {self.y}"
