"""Каталог предметов: название и три измеренных габарита."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from lsp_overlay.domain.errors import ValidationError

MIN_DIMENSION = 0.0
MAX_DIMENSION = 500.0


class Dimension(StrEnum):
    """Габарит предмета, который меряется отдельно."""

    LENGTH = "length"
    WIDTH = "width"
    HEIGHT = "height"

    @property
    def label(self) -> str:
        """Название для интерфейса и таблицы."""
        return {
            Dimension.LENGTH: "Длина",
            Dimension.WIDTH: "Ширина",
            Dimension.HEIGHT: "Высота",
        }[self]

    @property
    def short(self) -> str:
        """Короткая подпись для компактных строк."""
        return {"length": "Д", "width": "Ш", "height": "В"}[self.value]


@dataclass(frozen=True, slots=True)
class ObjectSpec:
    """Предмет с измеренными габаритами (метры)."""

    name: str
    length: float = 0.0
    width: float = 0.0
    height: float = 0.0

    def __post_init__(self) -> None:
        cleaned = self.name.strip()
        if not cleaned:
            raise ValidationError("название предмета не может быть пустым")
        object.__setattr__(self, "name", cleaned)
        for dimension in Dimension:
            value = getattr(self, dimension.value)
            if not math.isfinite(value):
                raise ValidationError(f"{dimension.label.lower()} должна быть числом")
            if not MIN_DIMENSION <= value <= MAX_DIMENSION:
                raise ValidationError(
                    f"{dimension.label.lower()} должна быть от {MIN_DIMENSION:g} "
                    f"до {MAX_DIMENSION:g} м"
                )

    @property
    def key(self) -> str:
        """Ключ сравнения названий без учёта регистра."""
        return self.name.casefold()

    def with_dimension(self, dimension: Dimension, value: float) -> ObjectSpec:
        """Копия с новым значением одного габарита."""
        if dimension is Dimension.LENGTH:
            return replace(self, length=value)
        if dimension is Dimension.WIDTH:
            return replace(self, width=value)
        return replace(self, height=value)

    def dimension(self, dimension: Dimension) -> float:
        """Значение габарита."""
        return float(getattr(self, dimension.value))

    @property
    def is_complete(self) -> bool:
        """Все три габарита измерены (не нулевые)."""
        return all(self.dimension(dimension) > 0.0 for dimension in Dimension)

    def matches(self, query: str) -> bool:
        """Поиск по названию без учёта регистра."""
        needle = query.strip().casefold()
        return not needle or needle in self.key

    def to_dict(self) -> dict[str, Any]:
        """Представление для JSON."""
        return {
            "name": self.name,
            "length": self.length,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, data: Any) -> ObjectSpec:
        """Разбирает запись из JSON."""
        if not isinstance(data, dict):
            raise ValidationError("предмет должен быть объектом JSON")
        try:
            return cls(
                name=str(data["name"]),
                length=float(data.get("length", 0.0)),
                width=float(data.get("width", 0.0)),
                height=float(data.get("height", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError(f"битая запись предмета: {error}") from error


@dataclass(frozen=True, slots=True)
class Catalog:
    """Список предметов с поиском по названию. Неизменяемый."""

    objects: tuple[ObjectSpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "objects", tuple(sorted(self.objects, key=_by_name)))

    @property
    def is_empty(self) -> bool:
        """В каталоге ничего нет."""
        return not self.objects

    def get(self, name: str) -> ObjectSpec | None:
        """Находит предмет по названию без учёта регистра."""
        key = name.strip().casefold()
        for spec in self.objects:
            if spec.key == key:
                return spec
        return None

    def upsert(self, spec: ObjectSpec) -> Catalog:
        """Добавляет предмет или обновляет уже сохранённый с тем же названием."""
        kept = tuple(existing for existing in self.objects if existing.key != spec.key)
        return Catalog(objects=(*kept, spec))

    def remove(self, name: str) -> Catalog:
        """Удаляет предмет по названию (отсутствие — не ошибка)."""
        key = name.strip().casefold()
        return Catalog(objects=tuple(item for item in self.objects if item.key != key))

    def find(self, query: str = "") -> tuple[ObjectSpec, ...]:
        """Предметы, в названии которых есть ``query`` (по алфавиту)."""
        return tuple(item for item in self.objects if item.matches(query))

    def to_dict(self) -> dict[str, Any]:
        """Представление для JSON."""
        return {"version": 1, "objects": [item.to_dict() for item in self.objects]}

    @classmethod
    def from_dict(cls, data: Any) -> Catalog:
        """Разбирает каталог из JSON; битые записи пропускаются."""
        if not isinstance(data, dict):
            raise ValidationError("каталог должен быть объектом JSON")
        raw = data.get("objects", [])
        if not isinstance(raw, list):
            raise ValidationError("поле «objects» должно быть списком")
        specs: list[ObjectSpec] = []
        for item in raw:
            try:
                specs.append(ObjectSpec.from_dict(item))
            except ValidationError:
                continue
        return cls(objects=tuple(sorted(specs, key=_by_name)))


def _by_name(spec: ObjectSpec) -> str:
    return spec.key
