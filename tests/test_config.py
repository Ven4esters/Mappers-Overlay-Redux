"""Настройки: значения по умолчанию, JSON и проверки."""

from __future__ import annotations

import pytest
from map_overlay.config import SCHEMA_VERSION, Delays, Settings
from map_overlay.domain.actions import DEFAULT_HOTKEYS, Action
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.point import Point
from map_overlay.errors import ConfigError


def test_defaults() -> None:
    settings = Settings()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.decimals == 3
    assert settings.verify_writes is True
    assert settings.default_step == 0.5
    assert settings.calibration == {}
    assert settings.missing_points() == PANEL_ORDER


def test_with_point_fills_calibration() -> None:
    settings = Settings().with_point(Field.X, Point(10, 20))
    assert settings.calibration == {Field.X: Point(10, 20)}
    assert Field.X not in settings.missing_points()


def test_to_dict_and_back_is_stable() -> None:
    settings = Settings().with_point(Field.RZ, Point(500, 260))
    restored = Settings.from_dict(settings.to_dict())
    assert restored == settings


def test_and_back_keeps_delays() -> None:
    settings = Settings(delays=Delays(click=0.1, select=0.2, copy=0.3, paste=0.4))
    assert Settings.from_dict(settings.to_dict()).delays == settings.delays


@pytest.mark.parametrize(
    "data",
    [
        {"schema_version": "1"},
        {"delays": []},
        {"delays": {"click": "быстро"}},
        {"decimals": "3"},
        {"verify_writes": "да"},
        {"default_step": -1},
        {"calibration": {"nope": {"x": 1, "y": 2}}},
        {"calibration": {"x": {"x": 1}}},
        {"calibration": {"x": {"x": 1.5, "y": 2}}},
    ],
)
def test_broken_data_is_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        Settings.from_dict(data)


def test_newer_schema_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings.from_dict({"schema_version": SCHEMA_VERSION + 1})


def test_unknown_keys_are_ignored() -> None:
    settings = Settings.from_dict({"schema_version": SCHEMA_VERSION, "future_key": 1})
    assert settings == Settings()


@pytest.mark.parametrize("decimals", [-1, 7])
def test_decimals_are_validated(decimals: int) -> None:
    with pytest.raises(ConfigError):
        Settings(decimals=decimals)


@pytest.mark.parametrize("step", [0.0, -1.0, 1000.0])
def test_default_step_is_validated(step: float) -> None:
    with pytest.raises(ConfigError):
        Settings(default_step=step)


@pytest.mark.parametrize("delay", [-0.5, 5.0])
def test_delays_are_validated(delay: float) -> None:
    with pytest.raises(ConfigError):
        Delays(click=delay)


def test_hotkeys_roundtrip() -> None:
    settings = Settings().with_hotkey(Action.CAPTURE, 0x70)
    restored = Settings.from_dict(settings.to_dict())
    assert restored.hotkeys[Action.CAPTURE] == 0x70
    assert restored == settings


def test_hotkey_takes_the_key_from_another_action() -> None:
    settings = Settings()
    previous_owner = Action.MOVE_FORWARD
    taken = settings.hotkeys[previous_owner]
    updated = settings.with_hotkey(Action.CAPTURE, taken)
    assert updated.hotkeys[Action.CAPTURE] == taken
    assert updated.hotkeys[previous_owner] is None
    keys = [key for key in updated.hotkeys.values() if key is not None]
    assert len(keys) == len(set(keys))


def test_hotkey_can_be_cleared() -> None:
    settings = Settings().with_hotkey(Action.CONFIRM, None)
    assert settings.hotkeys[Action.CONFIRM] is None


def test_duplicate_hotkeys_are_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings(hotkeys={Action.CAPTURE: 0x70, Action.CONFIRM: 0x70})


@pytest.mark.parametrize("vk", [0, 0xFF, "F1", -5])
def test_invalid_hotkey_code_is_rejected(vk: object) -> None:
    with pytest.raises(ConfigError):
        Settings(hotkeys={Action.CAPTURE: vk})  # type: ignore[dict-item]


def test_unknown_action_in_hotkeys_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings.from_dict({"schema_version": 2, "hotkeys": {"teleport": 0x70}})


def test_old_schema_gets_default_hotkeys() -> None:
    settings = Settings.from_dict({"schema_version": 1})
    assert settings.hotkeys == DEFAULT_HOTKEYS
    assert settings.empty_point is None


def test_empty_point_roundtrip() -> None:
    settings = Settings().with_empty_point(Point(640, 480))
    restored = Settings.from_dict(settings.to_dict())
    assert restored.empty_point == Point(640, 480)
    assert restored.has_confirmation_point()


def test_negative_empty_point_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings(empty_point=Point(-1, 0))


def test_negative_calibration_point_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings(calibration={Field.X: Point(-1, 0)})


def test_too_far_calibration_point_is_rejected() -> None:
    """Испорченный файл с ``1e18`` не должен превращаться в клик за пределы экрана."""
    raw = Settings().to_dict()
    raw["calibration"] = {"x": {"x": 10**18, "y": 10}}
    with pytest.raises(ConfigError, match="испорчен"):
        Settings.from_dict(raw)


def test_negative_schema_version_is_rejected() -> None:
    raw = Settings().to_dict()
    raw["schema_version"] = -1
    with pytest.raises(ConfigError, match="отрицательной"):
        Settings.from_dict(raw)
