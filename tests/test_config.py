"""Настройки: значения по умолчанию, JSON и проверки."""

from __future__ import annotations

import pytest
from map_overlay.config import SCHEMA_VERSION, Delays, Settings
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


def test_negative_calibration_point_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings(calibration={Field.X: Point(-1, 0)})
