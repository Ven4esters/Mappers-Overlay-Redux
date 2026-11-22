"""Настройки приложения: значения, сериализация, валидация.

Файл лежит отдельно от инфраструктуры, потому что настройки нужны и прикладному
слою (шаг, режим диагонали), и интерфейсу (прозрачность), и вводу (тайминги).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final

from lsp_overlay.domain.directions import DiagonalMode
from lsp_overlay.domain.fields import FIELD_ORDER, FieldKey
from lsp_overlay.domain.safety import DEFAULT_MAX_JUMP

SCHEMA_VERSION = 2
DEFAULT_STEP_PRESETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0)
DEFAULT_STEP = 0.1
CONFIRM_KEYS: tuple[str, ...] = ("f", "enter")
DEFAULT_CLONE_KEY = "c"
DEFAULT_CLONE_DELETE_KEY = "delete"
KEY_MAX_LENGTH = 20


class ConfigError(ValueError):
    """Файл настроек не соответствует схеме."""


@dataclass(frozen=True, slots=True)
class Point:
    """Точка на экране (физические пиксели)."""

    x: int
    y: int

    def as_tuple(self) -> tuple[int, int]:
        """Пара координат для API ввода."""
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class PanelTimings:
    """Паузы между действиями макроса, секунды."""

    click: float = 0.03
    field: float = 0.04
    paste: float = 0.04
    commit: float = 0.08
    focus: float = 0.12
    clipboard: float = 0.12

    def validated(self) -> PanelTimings:
        """Проверяет, что паузы в разумных пределах (0…1 с)."""
        for name in ("click", "field", "paste", "commit", "focus", "clipboard"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 2.0:
                raise ConfigError(f"пауза {name} должна быть в диапазоне 0…2 с")
        return self


@dataclass(frozen=True, slots=True)
class Calibration:
    """Точки полей панели и «пустое место» для подтверждения ввода."""

    fields: Mapping[FieldKey, Point] = field(default_factory=dict)
    placeholder: Point | None = None

    @classmethod
    def empty(cls) -> Calibration:
        """Пустая калибровка."""
        return cls(fields={}, placeholder=None)

    @property
    def is_complete(self) -> bool:
        """Все шесть полей и пустое место заданы."""
        return all(key in self.fields for key in FIELD_ORDER) and self.placeholder is not None

    @property
    def missing(self) -> tuple[FieldKey, ...]:
        """Каких полей не хватает."""
        return tuple(key for key in FIELD_ORDER if key not in self.fields)

    def with_point(self, key: FieldKey, point: Point) -> Calibration:
        """Копия калибровки с новой точкой поля."""
        return Calibration(fields={**self.fields, key: point}, placeholder=self.placeholder)

    def with_placeholder(self, point: Point) -> Calibration:
        """Копия калибровки с новой точкой подтверждения."""
        return Calibration(fields=dict(self.fields), placeholder=point)


@dataclass(frozen=True, slots=True)
class Settings:
    """Все пользовательские настройки."""

    step: float = DEFAULT_STEP
    step_presets: tuple[float, ...] = DEFAULT_STEP_PRESETS
    diagonal_mode: DiagonalMode = DiagonalMode.SAME_DISTANCE
    use_tilt: bool = True
    length_decimals: int = 4
    verify_after_paste: bool = True
    max_jump: float = DEFAULT_MAX_JUMP
    confirm_key: str = "f"
    clone_key: str = DEFAULT_CLONE_KEY
    clone_delete_key: str = DEFAULT_CLONE_DELETE_KEY
    calibration: Calibration = field(default_factory=Calibration.empty)
    timings: PanelTimings = field(default_factory=PanelTimings)
    overlay_opacity: float = 0.94
    always_on_top: bool = True

    def validated(self) -> Settings:
        """Проверяет инварианты и возвращает себя (удобно для цепочек)."""
        if not math.isfinite(self.step) or not 0.0 < self.step <= 500.0:
            raise ConfigError("шаг должен быть в диапазоне (0, 500] м")
        if not self.step_presets:
            raise ConfigError("список шагов не может быть пустым")
        if not 1 <= self.length_decimals <= 6:
            raise ConfigError("точность координат — от 1 до 6 знаков")
        if not math.isfinite(self.max_jump) or self.max_jump < 0.0:
            raise ConfigError("лимит шага не может быть отрицательным")
        if self.confirm_key not in CONFIRM_KEYS:
            raise ConfigError(f"клавиша подтверждения должна быть одной из {CONFIRM_KEYS}")
        clone_keys = (("клонирования", self.clone_key), ("удаления", self.clone_delete_key))
        for title, key in clone_keys:
            if not key.strip() or len(key) > KEY_MAX_LENGTH:
                raise ConfigError(f"клавиша {title} копии должна быть непустой строкой")
        if not 0.2 <= self.overlay_opacity <= 1.0:
            raise ConfigError("прозрачность оверлея — от 0.2 до 1.0")
        self.timings.validated()
        return self

    def with_step(self, step: float) -> Settings:
        """Копия с новым шагом."""
        return replace_settings(self, step=step).validated()

    def to_dict(self) -> dict[str, Any]:
        """Представление для JSON."""
        return {
            "version": SCHEMA_VERSION,
            "step": self.step,
            "step_presets": list(self.step_presets),
            "diagonal_mode": self.diagonal_mode.value,
            "use_tilt": self.use_tilt,
            "length_decimals": self.length_decimals,
            "verify_after_paste": self.verify_after_paste,
            "max_jump": self.max_jump,
            "confirm_key": self.confirm_key,
            "clone_key": self.clone_key,
            "clone_delete_key": self.clone_delete_key,
            "overlay_opacity": self.overlay_opacity,
            "always_on_top": self.always_on_top,
            "timings": {
                "click": self.timings.click,
                "field": self.timings.field,
                "paste": self.timings.paste,
                "commit": self.timings.commit,
                "focus": self.timings.focus,
                "clipboard": self.timings.clipboard,
            },
            "calibration": {
                "placeholder": list(self.calibration.placeholder.as_tuple())
                if self.calibration.placeholder
                else None,
                "fields": {
                    key.value: list(point.as_tuple())
                    for key, point in self.calibration.fields.items()
                },
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Settings:
        """Собирает настройки из JSON-словаря, игнорируя незнакомые ключи."""
        if not isinstance(data, Mapping):
            raise ConfigError("корень настроек должен быть объектом")
        timings_data = data.get("timings", {})
        calibration_data = data.get("calibration", {})
        if not isinstance(timings_data, Mapping) or not isinstance(calibration_data, Mapping):
            raise ConfigError("timings и calibration должны быть объектами")
        return cls(
            step=float(data.get("step", DEFAULT_STEP)),
            step_presets=tuple(
                float(value) for value in data.get("step_presets", DEFAULT_STEP_PRESETS)
            ),
            diagonal_mode=DiagonalMode(data.get("diagonal_mode", DiagonalMode.SAME_DISTANCE.value)),
            use_tilt=bool(data.get("use_tilt", True)),
            length_decimals=int(data.get("length_decimals", 4)),
            verify_after_paste=bool(data.get("verify_after_paste", True)),
            max_jump=float(data.get("max_jump", DEFAULT_MAX_JUMP)),
            confirm_key=str(data.get("confirm_key", "f")).lower(),
            clone_key=str(data.get("clone_key", DEFAULT_CLONE_KEY)).lower(),
            clone_delete_key=str(data.get("clone_delete_key", DEFAULT_CLONE_DELETE_KEY)).lower(),
            overlay_opacity=float(data.get("overlay_opacity", 0.94)),
            always_on_top=bool(data.get("always_on_top", True)),
            timings=_timings_from(timings_data),
            calibration=_calibration_from(calibration_data),
        ).validated()


def replace_settings(settings: Settings, **changes: Any) -> Settings:
    """``dataclasses.replace`` без импорта в каждом модуле UI."""
    return replace(settings, **changes)


def _point(value: Any) -> Point | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:  # noqa: PLR2004 - пара координат
        raise ConfigError("точка калибровки — пара [x, y]")
    try:
        return Point(x=int(value[0]), y=int(value[1]))
    except (TypeError, ValueError) as error:
        raise ConfigError("координаты точки должны быть целыми") from error


LEGACY_TIMINGS: Final[dict[str, float]] = {
    "click": 0.08,
    "field": 0.10,
    "paste": 0.10,
    "commit": 0.18,
    "focus": 0.20,
}


def _timings_from(data: Mapping[str, Any]) -> PanelTimings:
    """Читает паузы; файлы от версий ≤ 2.4.1 переводятся на новые быстрые значения."""
    defaults = PanelTimings()
    if "clipboard" not in data and all(
        float(data.get(name, value)) == value for name, value in LEGACY_TIMINGS.items()
    ):
        return defaults
    return PanelTimings(
        click=float(data.get("click", defaults.click)),
        field=float(data.get("field", defaults.field)),
        paste=float(data.get("paste", defaults.paste)),
        commit=float(data.get("commit", defaults.commit)),
        focus=float(data.get("focus", defaults.focus)),
        clipboard=float(data.get("clipboard", defaults.clipboard)),
    )


def _calibration_from(data: Mapping[str, Any]) -> Calibration:
    raw_fields = data.get("fields", {})
    if not isinstance(raw_fields, Mapping):
        raise ConfigError("calibration.fields должен быть объектом")
    fields: dict[FieldKey, Point] = {}
    for key, value in raw_fields.items():
        try:
            field_key = FieldKey(str(key))
        except ValueError as error:
            raise ConfigError(f"неизвестное поле калибровки: {key}") from error
        point = _point(value)
        if point is not None:
            fields[field_key] = point
    return Calibration(fields=fields, placeholder=_point(data.get("placeholder")))
