from __future__ import annotations

import pytest
from lsp_overlay.config import (
    MOVE_SPACE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    Calibration,
    ConfigError,
    Point,
    Settings,
)
from lsp_overlay.domain.fields import FIELD_ORDER
from lsp_overlay.domain.movement import MoveSpace


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


def test_move_space_round_trip() -> None:
    settings = Settings(move_frame=MoveSpace.WORLD)
    assert Settings.from_dict(settings.to_dict()).move_frame is MoveSpace.WORLD
    assert Settings().move_frame is MoveSpace.OBJECT


@pytest.mark.parametrize("legacy", ["world", "prop"])
def test_old_move_space_names_become_object(legacy: str) -> None:
    """Файлы 2.9–2.11 читаются как «по углу предмета», как в первой версии."""
    old = Settings().to_dict()
    old["version"] = MOVE_SPACE_SCHEMA_VERSION - 1
    old["move_space"] = legacy
    old.pop("move_frame", None)
    assert Settings.from_dict(old).move_frame is MoveSpace.OBJECT


def test_old_schema_world_value_is_migrated() -> None:
    """Ключ move_frame из 2.10.x тоже читается."""
    old = Settings().to_dict()
    old["version"] = 2
    old.pop("move_space")
    old["move_frame"] = "world"
    assert Settings.from_dict(old).move_frame is MoveSpace.OBJECT


def test_tilt_is_on_by_default_like_the_first_release() -> None:
    """В первой версии 2.0 (коммит d2db3d0) наклоны RX/RY учитывались."""
    assert Settings().use_tilt is True


def test_anchor_and_inverts_round_trip() -> None:
    settings = Settings(
        anchor_rz=70.0, invert_forward=True, invert_right=True, invert_up=True, invert_rotate=True
    )
    restored = Settings.from_dict(settings.to_dict())
    assert restored.anchor_rz == pytest.approx(70.0)
    assert restored.invert == settings.invert
    assert restored.invert_rotate is True


def test_anchor_out_of_range_is_rejected() -> None:
    with pytest.raises(ConfigError, match="якорь"):
        Settings(anchor_rz=1000.0).validated()


def test_unknown_move_frame_is_rejected() -> None:
    data = Settings().to_dict()
    data["move_space"] = "лунные оси"
    with pytest.raises(ConfigError, match="оси движения"):
        Settings.from_dict(data)


def test_move_rotation_round_trip() -> None:
    settings = Settings(move_rotation=45.0)
    assert Settings.from_dict(settings.to_dict()).move_rotation == pytest.approx(45.0)
    assert Settings().move_rotation == 0.0


def test_move_rotation_out_of_range_is_rejected() -> None:
    with pytest.raises(ConfigError, match="поворот осей"):
        Settings(move_rotation=400.0).validated()


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


def test_default_timings_are_fast() -> None:
    from lsp_overlay.config import PanelTimings

    timings = PanelTimings()
    assert timings.click <= 0.05
    assert timings.field <= 0.05
    assert timings.commit <= 0.1
    assert timings.clipboard <= 0.2


def test_clipboard_timeout_survives_json_roundtrip() -> None:
    from lsp_overlay.config import PanelTimings, Settings

    settings = Settings(timings=PanelTimings(clipboard=0.3))
    restored = Settings.from_dict(settings.to_dict())
    assert restored.timings.clipboard == pytest.approx(0.3)


def test_legacy_timings_are_migrated_to_fast_defaults() -> None:
    from lsp_overlay.config import PanelTimings, Settings

    legacy = {
        "click": 0.08,
        "field": 0.10,
        "paste": 0.10,
        "commit": 0.18,
        "focus": 0.20,
    }
    settings = Settings.from_dict({"timings": legacy})
    assert settings.timings == PanelTimings()


def test_custom_timings_are_kept() -> None:
    from lsp_overlay.config import Settings

    settings = Settings.from_dict({"timings": {"click": 0.05, "field": 0.2}})
    assert settings.timings.click == pytest.approx(0.05)
    assert settings.timings.field == pytest.approx(0.2)


def test_live_commit_is_off_by_default() -> None:
    assert Settings().live_commit is False


def test_live_commit_survives_json_roundtrip() -> None:
    settings = Settings(live_commit=True)
    restored = Settings.from_dict(settings.to_dict())
    assert restored.live_commit is True


def test_old_settings_file_without_live_commit_keeps_f_off() -> None:
    data = Settings().to_dict()
    data.pop("live_commit")
    assert Settings.from_dict(data).live_commit is False


def test_live_hold_timeout_default_and_roundtrip() -> None:
    assert Settings().live_hold_timeout == pytest.approx(1.0)
    restored = Settings.from_dict(Settings(live_hold_timeout=2.5).to_dict())
    assert restored.live_hold_timeout == pytest.approx(2.5)


def test_live_hold_timeout_is_validated() -> None:
    for value in (0.05, 0.0, -1.0, 30.0):
        with pytest.raises(ConfigError):
            Settings(live_hold_timeout=value).validated()
