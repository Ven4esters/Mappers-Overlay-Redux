"""Библиотека размеров предметов: название, длина и ширина в метрах.

Размеры нужны, чтобы шаг совпадал с габаритом предмета: «длина» ставит следующий
предмет вплотную, «полширины» — центром на край. Хранится библиотека отдельным
файлом (``config/sizes.json``), рядом с настройками.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from map_overlay.errors import ConfigError, ValidationError

SCHEMA_VERSION: Final = 1
MIN_SIZE_M: Final = 0.01
MAX_SIZE_M: Final = 1000.0
# Допустимые габариты: от сантиметра до километра. Больше — уже не предмет.

MAX_NAME_LEN: Final = 60
MAX_ITEMS: Final = 200
# Пределы библиотеки: защита от случайной вставки огромного файла.

SIZE_DECIMALS: Final = 3


@dataclass(frozen=True, slots=True)
class ObjectSize:
    """Предмет из библиотеки: название и габариты.

    Raises:
        ValidationError: если название пустое или габариты вне допустимых пределов.
    """

    name: str
    length: float
    width: float

    def __post_init__(self) -> None:
        text = self.name.strip()
        if not text:
            raise ValidationError("Название предмета не может быть пустым")
        if len(text) > MAX_NAME_LEN:
            raise ValidationError(f"Название длиннее {MAX_NAME_LEN} символов")
        object.__setattr__(self, "name", text)
        _check_size(self.length, "Длина")
        _check_size(self.width, "Ширина")

    @property
    def key(self) -> str:
        """Ключ сравнения названий: регистр и пробелы по краям не важны."""
        return self.name.casefold()

    @property
    def half_length(self) -> float:
        """Половина длины: шаг от центра до края."""
        return self.length / 2

    @property
    def half_width(self) -> float:
        """Половина ширины: шаг от центра до края."""
        return self.width / 2

    def text(self) -> str:
        """Строка для интерфейса: «Ящик · 2 × 1.2 м»."""
        return f"{self.name} · {self.length:g} × {self.width:g} м"


class SizeUse(StrEnum):
    """Что берём из размера, чтобы получить шаг."""

    LENGTH = "length"
    WIDTH = "width"
    HALF_LENGTH = "half_length"
    HALF_WIDTH = "half_width"

    @property
    def label(self) -> str:
        """Название кнопки."""
        return _USE_TITLES[self]

    @property
    def hint(self) -> str:
        """Подсказка: что даёт такой шаг."""
        return _USE_HINTS[self]

    def value_for(self, size: ObjectSize) -> float:
        """Значение шага для этого размера."""
        if self is SizeUse.LENGTH:
            return size.length
        if self is SizeUse.WIDTH:
            return size.width
        if self is SizeUse.HALF_LENGTH:
            return size.half_length
        return size.half_width


SIZE_USES: Final[tuple[SizeUse, ...]] = (
    SizeUse.LENGTH,
    SizeUse.WIDTH,
    SizeUse.HALF_LENGTH,
    SizeUse.HALF_WIDTH,
)
# Порядок кнопок «в шаг» на вкладке движения.

_USE_TITLES: Final[dict[SizeUse, str]] = {
    SizeUse.LENGTH: "Длина",
    SizeUse.WIDTH: "Ширина",
    SizeUse.HALF_LENGTH: "½ длины",
    SizeUse.HALF_WIDTH: "½ ширины",
}

_USE_HINTS: Final[dict[SizeUse, str]] = {
    SizeUse.LENGTH: "шаг равен длине: следующий предмет встанет вплотную по длине",
    SizeUse.WIDTH: "шаг равен ширине: следующий предмет встанет вплотную по ширине",
    SizeUse.HALF_LENGTH: "половина длины: центр предмета встанет на прежний край",
    SizeUse.HALF_WIDTH: "половина ширины: центр предмета встанет на прежний край",
}


@dataclass(frozen=True, slots=True)
class SizeLibrary:
    """Библиотека предметов и выбранный предмет для шагов.

    Raises:
        ConfigError: если названия повторяются или выбранного предмета нет.
    """

    items: tuple[ObjectSize, ...] = ()
    active: str | None = None

    def __post_init__(self) -> None:
        _check_items(self.items)
        if self.active is not None and self.find(self.active) is None:
            raise ConfigError(f"Выбранный предмет «{self.active}» отсутствует в библиотеке")

    @property
    def active_item(self) -> ObjectSize | None:
        """Выбранный предмет (``None`` — ничего не выбрано)."""
        return None if self.active is None else self.find(self.active)

    def find(self, name: str) -> ObjectSize | None:
        """Найти предмет по названию без учёта регистра."""
        key = name.strip().casefold()
        return next((item for item in self.items if item.key == key), None)

    def with_item(self, item: ObjectSize) -> SizeLibrary:
        """Добавить предмет или заменить одноимённый.

        Первый предмет пустой библиотеки сразу становится выбранным: добавил — и
        можно брать его размер в шаг.

        Raises:
            ValidationError: если библиотека переполнена.
        """
        known = any(existing.key == item.key for existing in self.items)
        items = [item if existing.key == item.key else existing for existing in self.items]
        if not known:
            if len(items) >= MAX_ITEMS:
                raise ValidationError(f"В библиотеке уже {MAX_ITEMS} предметов: удалите лишние")
            items.append(item)
        active = self.active
        if not self.items or (active is not None and active.casefold() == item.key):
            active = item.name
        return SizeLibrary(items=tuple(items), active=active)

    def without(self, name: str) -> SizeLibrary:
        """Удалить предмет по названию; выбранный предмет при удалении сбрасывается."""
        key = name.strip().casefold()
        items = tuple(item for item in self.items if item.key != key)
        if len(items) == len(self.items):
            return self
        active = None if self.active is not None and self.active.casefold() == key else self.active
        return SizeLibrary(items=items, active=active)

    def select(self, name: str | None) -> SizeLibrary:
        """Выбрать предмет для шагов (``None`` — снять выбор).

        Raises:
            ValidationError: если такого предмета нет.
        """
        if name is None:
            return SizeLibrary(items=self.items, active=None)
        found = self.find(name)
        if found is None:
            raise ValidationError(f"Предмета «{name.strip()}» нет в библиотеке")
        return SizeLibrary(items=self.items, active=found.name)

    def to_dict(self) -> dict[str, Any]:
        """Данные для записи в JSON."""
        return {
            "schema_version": SCHEMA_VERSION,
            "active": self.active,
            "items": [
                {"name": item.name, "length": item.length, "width": item.width}
                for item in self.items
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SizeLibrary:
        """Собрать библиотеку из JSON-словаря с проверкой типов.

        Raises:
            ConfigError: если структура или значения недопустимы.
        """
        raw = _as_mapping(data, "библиотека размеров")
        version = _as_int(raw.get("schema_version", SCHEMA_VERSION), "schema_version")
        if version > SCHEMA_VERSION:
            raise ConfigError(
                f"Файл размеров новее приложения (схема {version}, поддерживается "
                f"{SCHEMA_VERSION}). Обновите оверлей."
            )
        entries = raw.get("items", [])
        if not isinstance(entries, list):
            raise ConfigError("Ожидался список предметов в поле «items»")
        active_raw = raw.get("active")
        try:
            return cls(
                items=tuple(_parse_item(entry) for entry in entries),
                active=None if active_raw is None else _as_str(active_raw, "active"),
            )
        except ValidationError as exc:
            raise ConfigError(f"Библиотека размеров испорчена: {exc}") from exc


def _check_size(value: float, title: str) -> None:
    if not math.isfinite(value):
        raise ValidationError(f"{title} должна быть числом")
    if not MIN_SIZE_M <= value <= MAX_SIZE_M:
        raise ValidationError(
            f"{title} должна быть от {MIN_SIZE_M:g} до {MAX_SIZE_M:g} м, получено {value:g}"
        )


def _check_items(items: tuple[ObjectSize, ...]) -> None:
    if len(items) > MAX_ITEMS:
        raise ConfigError(f"В библиотеке больше {MAX_ITEMS} предметов")
    seen: set[str] = set()
    for item in items:
        if item.key in seen:
            raise ConfigError(f"Предмет «{item.name}» встречается в библиотеке дважды")
        seen.add(item.key)


def _parse_item(value: object) -> ObjectSize:
    raw = _as_mapping(value, "предмет")
    return ObjectSize(
        name=_as_str(raw.get("name"), "название предмета"),
        length=_as_float(raw.get("length"), "длина предмета"),
        width=_as_float(raw.get("width"), "ширина предмета"),
    )


def _as_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"Ожидался объект в поле «{name}»")
    return value


def _as_str(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"Поле «{name}» должно быть строкой")
    return value


def _as_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"Поле «{name}» должно быть числом")
    return float(value)


def _as_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Поле «{name}» должно быть целым числом")
    return value
