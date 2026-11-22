"""Настройки приложения: задержки, точность, калибровка полей."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final

from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.formatting import MAX_DECIMALS, MIN_DECIMALS
from map_overlay.domain.movement import validate_step
from map_overlay.domain.point import Point
from map_overlay.errors import ConfigError

SCHEMA_VERSION: Final = 1
DEFAULT_STEP: Final = 0.5
DEFAULT_DECIMALS: Final = 3

MIN_DELAY_S: Final = 0.0
MAX_DELAY_S: Final = 2.0


@dataclass(frozen=True, slots=True)
class Delays:
    """Паузы между шагами обмена с панелью, в секундах."""

    click: float = 0.06
    select: float = 0.05
    copy: float = 0.05
    paste: float = 0.08

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            if not MIN_DELAY_S <= value <= MAX_DELAY_S:
                raise ConfigError(
                    f"Задержка «{name}» должна быть от {MIN_DELAY_S} до {MAX_DELAY_S} с, "
                    f"получено {value}"
                )

    def to_dict(self) -> dict[str, float]:
        """Представление для файла настроек."""
        return {
            "click": self.click,
            "select": self.select,
            "copy": self.copy,
            "paste": self.paste,
        }


@dataclass(frozen=True, slots=True)
class Settings:
    """Все настройки оверлея одним неизменяемым объектом."""

    schema_version: int = SCHEMA_VERSION
    delays: Delays = field(default_factory=Delays)
    decimals: int = DEFAULT_DECIMALS
    verify_writes: bool = True
    default_step: float = DEFAULT_STEP
    calibration: Mapping[Field, Point] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not MIN_DECIMALS <= self.decimals <= MAX_DECIMALS:
            raise ConfigError(
                f"Знаков после запятой должно быть от {MIN_DECIMALS} до {MAX_DECIMALS}, "
                f"получено {self.decimals}"
            )
        try:
            validate_step(self.default_step)
        except Exception as exc:
            raise ConfigError(f"Шаг по умолчанию недопустим: {exc}") from exc
        for field_name, point in self.calibration.items():
            if field_name not in PANEL_ORDER:
                raise ConfigError(f"Неизвестное поле в калибровке: {field_name}")
            if point.x < 0 or point.y < 0:
                raise ConfigError(f"Координаты поля {field_name} не могут быть отрицательными")

    def missing_points(self) -> tuple[Field, ...]:
        """Поля, для которых ещё не задана точка."""
        return tuple(field_name for field_name in PANEL_ORDER if field_name not in self.calibration)

    def with_point(self, field_name: Field, point: Point) -> Settings:
        """Копия настроек с новой точкой калибровки."""
        calibration = dict(self.calibration)
        calibration[field_name] = point
        return replace(self, calibration=calibration)

    def with_calibration(self, calibration: Mapping[Field, Point]) -> Settings:
        """Копия настроек с целой картой калибровки."""
        return replace(self, calibration=dict(calibration))

    def to_dict(self) -> dict[str, Any]:
        """Данные для записи в JSON."""
        return {
            "schema_version": self.schema_version,
            "delays": self.delays.to_dict(),
            "decimals": self.decimals,
            "verify_writes": self.verify_writes,
            "default_step": self.default_step,
            "calibration": {
                field_name.value: {"x": point.x, "y": point.y}
                for field_name, point in self.calibration.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Settings:
        """Собрать настройки из JSON-словаря с проверкой типов.

        Raises:
            ConfigError: если структура или значения недопустимы.
        """
        raw = _as_mapping(data, "настройки")
        version = _as_int(raw.get("schema_version", SCHEMA_VERSION), "schema_version")
        if version > SCHEMA_VERSION:
            raise ConfigError(
                f"Файл настроек новее приложения (схема {version}, поддерживается "
                f"{SCHEMA_VERSION}). Обновите оверлей."
            )
        delays_raw = _as_mapping(raw.get("delays", {}), "delays")
        defaults = Delays()
        delays = Delays(
            click=_as_float(delays_raw.get("click", defaults.click), "задержка клика"),
            select=_as_float(delays_raw.get("select", defaults.select), "задержка выделения"),
            copy=_as_float(delays_raw.get("copy", defaults.copy), "задержка копирования"),
            paste=_as_float(delays_raw.get("paste", defaults.paste), "задержка вставки"),
        )
        calibration = _parse_calibration(raw.get("calibration", {}))
        return cls(
            schema_version=version,
            delays=delays,
            decimals=_as_int(raw.get("decimals", DEFAULT_DECIMALS), "decimals"),
            verify_writes=_as_bool(raw.get("verify_writes", True), "verify_writes"),
            default_step=_as_float(raw.get("default_step", DEFAULT_STEP), "шаг по умолчанию"),
            calibration=calibration,
        )


def _as_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"Ожидался объект в поле «{name}»")
    return value


def _as_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"Поле «{name}» должно быть числом")
    return float(value)


def _as_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Поле «{name}» должно быть целым числом")
    return value


def _as_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"Поле «{name}» должно быть true или false")
    return value


def _parse_calibration(value: object) -> dict[Field, Point]:
    raw = _as_mapping(value, "calibration")
    calibration: dict[Field, Point] = {}
    for key, point in raw.items():
        try:
            field_name = Field(key)
        except ValueError as exc:
            raise ConfigError(f"Неизвестное поле в калибровке: {key}") from exc
        point_data = _as_mapping(point, f"точка {key}")
        calibration[field_name] = Point(
            x=_as_int(point_data.get("x"), f"x точки {key}"),
            y=_as_int(point_data.get("y"), f"y точки {key}"),
        )
    return calibration
