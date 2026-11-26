"""Настройки приложения: задержки, точность, калибровка полей."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final

from map_overlay.domain.actions import DEFAULT_HOTKEYS, Action
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.formatting import MAX_DECIMALS, MIN_DECIMALS
from map_overlay.domain.keynames import is_valid_vk
from map_overlay.domain.movement import validate_step
from map_overlay.domain.point import Point
from map_overlay.errors import ConfigError

SCHEMA_VERSION: Final = 2
MAX_POINT_COORDINATE: Final = 100_000
# Верхняя граница для точек калибровки: защита от испорченного файла с ``1e18``.
DEFAULT_STEP: Final = 0.5
DEFAULT_DECIMALS: Final = 3

DEFAULT_SELF_WRITE_GRACE_S: Final = 2.0
MIN_SELF_WRITE_GRACE_S: Final = 0.0
MAX_SELF_WRITE_GRACE_S: Final = 10.0
# Пауза, в течение которой оверлей не перечитывает X после своей же записи (ADR-0051).

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
    self_write_grace: float = DEFAULT_SELF_WRITE_GRACE_S
    # Сколько секунд после своей записи не перечитывать поле X: 0 — сверять всегда.
    always_read_pose: bool = False
    # «Всегда считать позицию»: перед каждым нажатием направления оверлей сам читает
    # поля панели, поэтому «Считать» для шага больше не требуется.
    straight_cardinal: bool = False
    # «Прямой шаг 4/6/8/2»: при RX/RY ≠ 0 клавиши движения идут по мировым осям,
    # а высота — строго по Z. По умолчанию выключено: формулы поворота остаются прежними.
    default_step: float = DEFAULT_STEP
    calibration: Mapping[Field, Point] = field(default_factory=dict)
    empty_point: Point | None = None
    hotkeys: Mapping[Action, int | None] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    def __post_init__(self) -> None:
        if not MIN_DECIMALS <= self.decimals <= MAX_DECIMALS:
            raise ConfigError(
                f"Знаков после запятой должно быть от {MIN_DECIMALS} до {MAX_DECIMALS}, "
                f"получено {self.decimals}"
            )
        if not MIN_SELF_WRITE_GRACE_S <= self.self_write_grace <= MAX_SELF_WRITE_GRACE_S:
            raise ConfigError(
                f"Пауза доверия к своей записи должна быть от {MIN_SELF_WRITE_GRACE_S} до "
                f"{MAX_SELF_WRITE_GRACE_S} с, получено {self.self_write_grace}"
            )
        try:
            validate_step(self.default_step)
        except Exception as exc:
            raise ConfigError(f"Шаг по умолчанию недопустим: {exc}") from exc
        for field_name, point in self.calibration.items():
            if field_name not in PANEL_ORDER:
                raise ConfigError(f"Неизвестное поле в калибровке: {field_name}")
            _check_point(point, field_name.value)
        if self.empty_point is not None:
            _check_point(self.empty_point, "empty")
        _check_hotkeys(self.hotkeys)

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

    def with_empty_point(self, point: Point | None) -> Settings:
        """Копия настроек с точкой «пустое место панели»."""
        return replace(self, empty_point=point)

    def with_hotkey(self, action: Action, vk: int | None) -> Settings:
        """Копия настроек с новой клавишей действия.

        Если клавиша уже занята другим действием, старая привязка снимается:
        две команды на одну клавишу — источник путаницы.
        """
        hotkeys = {
            bound_action: (None if bound_key == vk else bound_key)
            for bound_action, bound_key in self.hotkeys.items()
        }
        hotkeys[action] = vk
        return replace(self, hotkeys=hotkeys)

    def has_confirmation_point(self) -> bool:
        """Есть ли точка для клика перед клавишей F."""
        return self.empty_point is not None

    def to_dict(self) -> dict[str, Any]:
        """Данные для записи в JSON."""
        return {
            "schema_version": self.schema_version,
            "delays": self.delays.to_dict(),
            "decimals": self.decimals,
            "verify_writes": self.verify_writes,
            "self_write_grace": self.self_write_grace,
            "always_read_pose": self.always_read_pose,
            "straight_cardinal": self.straight_cardinal,
            "default_step": self.default_step,
            "calibration": {
                field_name.value: {"x": point.x, "y": point.y}
                for field_name, point in self.calibration.items()
            },
            "empty_point": _point_to_dict(self.empty_point),
            "hotkeys": {
                action.value: key for action, key in self.hotkeys.items() if key is not None
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
        if version < 0:
            raise ConfigError(f"Версия файла настроек не может быть отрицательной: {version}")
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
        empty_point = _parse_optional_point(raw.get("empty_point"), "empty_point")
        hotkeys = _parse_hotkeys(raw.get("hotkeys"))
        return cls(
            schema_version=version,
            delays=delays,
            decimals=_as_int(raw.get("decimals", DEFAULT_DECIMALS), "decimals"),
            verify_writes=_as_bool(raw.get("verify_writes", True), "verify_writes"),
            self_write_grace=_as_float(
                raw.get("self_write_grace", DEFAULT_SELF_WRITE_GRACE_S),
                "пауза доверия к своей записи",
            ),
            always_read_pose=_as_bool(raw.get("always_read_pose", False), "always_read_pose"),
            straight_cardinal=_as_bool(raw.get("straight_cardinal", False), "straight_cardinal"),
            default_step=_as_float(raw.get("default_step", DEFAULT_STEP), "шаг по умолчанию"),
            calibration=calibration,
            empty_point=empty_point,
            hotkeys=hotkeys,
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


def _check_point(point: Point, name: str) -> None:
    if point.x < 0 or point.y < 0:
        raise ConfigError(f"Координаты точки «{name}» не могут быть отрицательными")
    if point.x > MAX_POINT_COORDINATE or point.y > MAX_POINT_COORDINATE:
        raise ConfigError(
            f"Координаты точки «{name}» больше {MAX_POINT_COORDINATE} пикселей: "
            "файл настроек испорчен"
        )


def _check_hotkeys(hotkeys: Mapping[Action, int | None]) -> None:
    used: dict[int, Action] = {}
    for action, vk in hotkeys.items():
        if action not in Action:
            raise ConfigError(f"Неизвестное действие в горячих клавишах: {action}")
        if vk is None:
            continue
        if not is_valid_vk(vk):
            raise ConfigError(f"Клавиша для «{action}» имеет недопустимый код {vk!r}")
        if vk in used:
            raise ConfigError(f"Клавиша {vk} назначена дважды: «{used[vk]}» и «{action}»")
        used[vk] = action


def _point_to_dict(point: Point | None) -> dict[str, int] | None:
    if point is None:
        return None
    return {"x": point.x, "y": point.y}


def _parse_hotkeys(value: object) -> dict[Action, int | None]:
    if value is None:
        return dict(DEFAULT_HOTKEYS)
    raw = _as_mapping(value, "hotkeys")
    hotkeys: dict[Action, int | None] = {}
    for key, vk in raw.items():
        try:
            action = Action(key)
        except ValueError as exc:
            raise ConfigError(f"Неизвестное действие в горячих клавишах: {key}") from exc
        if vk is not None and not is_valid_vk(vk):
            raise ConfigError(f"Клавиша для «{key}» имеет недопустимый код {vk!r}")
        hotkeys[action] = vk
    for action, default_vk in DEFAULT_HOTKEYS.items():
        hotkeys.setdefault(action, default_vk)
    return hotkeys


def _parse_optional_point(value: object, name: str) -> Point | None:
    if value is None:
        return None
    raw = _as_mapping(value, name)
    return Point(
        x=_as_int(raw.get("x"), f"x точки {name}"),
        y=_as_int(raw.get("y"), f"y точки {name}"),
    )


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
