from __future__ import annotations

import pytest
from lsp_overlay.config import (
    SCHEMA_VERSION,
    Calibration,
    ConfigError,
    Point,
    Settings,
)
from lsp_overlay.domain.fields import FIELD_ORDER


def test_defaults_are_valid() -> None:
    settings = Settings().validated()
    assert settings.confirm_key == "f"
    assert settings.verify_after_paste is True
    assert settings.diagonal_mode.value == "same_distance"


def test_round_trip_keeps_values() -> None:
    calibration = Calibration.empty()
    for index, key in enumerate(FIELD_ORDER):
        calibration = calibration.with_point(key, Point(100 + index, 200 + index))
    calibration = calibration.with_placeholder(Point(50, 60))
    original = Settings(step=0.25, max_jump=35.0, calibration=calibration)
    restored = Settings.from_dict(original.to_dict())
    assert restored == original


def test_serialized_document_has_version() -> None:
    assert Settings().to_dict()["version"] == SCHEMA_VERSION


def test_unknown_keys_are_ignored() -> None:
    data = Settings().to_dict()
    data["future_option"] = "значение"
    assert Settings.from_dict(data) == Settings()


@pytest.mark.parametrize("step", [0.0, -1.0, 1000.0, float("nan")])
def test_invalid_step_is_rejected(step: float) -> None:
    with pytest.raises(ConfigError):
        Settings(step=step).validated()


def test_empty_presets_rejected() -> None:
    with pytest.raises(ConfigError, match="шагов"):
        Settings(step_presets=()).validated()


def test_unknown_confirm_key_rejected() -> None:
    with pytest.raises(ConfigError, match="подтверждения"):
        Settings(confirm_key="space").validated()


def test_opacity_bounds() -> None:
    with pytest.raises(ConfigError, match="прозрачность"):
        Settings(overlay_opacity=0.0).validated()


def test_negative_max_jump_rejected() -> None:
    with pytest.raises(ConfigError, match="лимит"):
        Settings(max_jump=-1.0).validated()


def test_calibration_completeness() -> None:
    calibration = Calibration.empty()
    assert not calibration.is_complete
    assert calibration.missing == FIELD_ORDER
    for key in FIELD_ORDER:
        calibration = calibration.with_point(key, Point(1, 2))
    assert not calibration.is_complete  # не хватает «пустого места»
    calibration = calibration.with_placeholder(Point(5, 5))
    assert calibration.is_complete
    assert calibration.missing == ()


def test_bad_calibration_point_is_rejected() -> None:
    data = Settings().to_dict()
    data["calibration"] = {"fields": {"x": [1, 2, 3]}, "placeholder": None}
    with pytest.raises(ConfigError, match="пара"):
        Settings.from_dict(data)


def test_unknown_calibration_field_is_rejected() -> None:
    data = Settings().to_dict()
    data["calibration"] = {"fields": {"q": [1, 2]}, "placeholder": None}
    with pytest.raises(ConfigError, match="неизвестное поле"):
        Settings.from_dict(data)


def test_non_object_root_is_rejected() -> None:
    with pytest.raises(ConfigError, match="объектом"):
        Settings.from_dict([])  # type: ignore[arg-type]
