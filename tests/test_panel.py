from __future__ import annotations

import pytest
from lsp_overlay.application.errors import PanelUnavailableError
from lsp_overlay.config import Calibration, PanelTimings
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.pose import Pose
from lsp_overlay.infrastructure.panel import ClipboardPanel

from fakes import FakeClipboard, FakeInput, FakeLspGame, build_calibration

POSE = Pose(x=250.5, y=-810.25, z=31.0, rx=0.0, ry=0.0, rz=127.42)


def make_panel(
    *,
    drop_select_all: bool = False,
    calibration: Calibration | None = None,
    ready: bool = True,
) -> tuple[ClipboardPanel, FakeLspGame, FakeInput]:
    clipboard = FakeClipboard()
    calibration = calibration or build_calibration()
    game = FakeLspGame(
        calibration,
        POSE,
        clipboard,
        drop_select_all=drop_select_all,
    )
    fake_input = FakeInput(game, ready=ready)
    panel = ClipboardPanel(
        fake_input,
        clipboard,
        calibration=calibration,
        timings=PanelTimings(click=0.0, field=0.0, paste=0.0, commit=0.0),
        sleep=lambda _seconds: None,
    )
    return panel, game, fake_input


def test_read_pose_returns_all_fields() -> None:
    panel, _game, _input = make_panel()
    assert panel.read_pose() == POSE


def test_read_field_uses_select_all_and_copy() -> None:
    panel, _game, fake_input = make_panel()
    assert panel.read_field(FieldKey.Z) == pytest.approx(31.0)
    assert ("combo", "ctrl+a") in fake_input.events
    assert ("combo", "ctrl+c") in fake_input.events


def test_write_fields_touches_only_requested_fields() -> None:
    panel, game, _input = make_panel()
    panel.write_fields({FieldKey.X: 251.0})
    assert game.pose.x == pytest.approx(251.0)
    assert game.pose.y == pytest.approx(POSE.y)


def test_written_angle_is_plain_number_without_degree_sign() -> None:
    panel, game, _input = make_panel()
    panel.write_fields({FieldKey.RZ: 90.0})
    assert game.pose.rz == pytest.approx(90.0)
    assert game.clipboard.text == "90.00"


def test_commit_clicks_placeholder_and_presses_confirm_key_without_enter() -> None:
    panel, game, fake_input = make_panel()
    panel.commit()
    assert game.commits == 1
    assert game.last_confirm_key == "f"
    assert ("key", "enter") not in fake_input.events
    assert ("click", "900,900") in fake_input.events


def test_commit_uses_configured_key() -> None:
    clipboard = FakeClipboard()
    calibration = build_calibration()
    game = FakeLspGame(calibration, POSE, clipboard, confirm_key="enter")
    fake_input = FakeInput(game)
    panel = ClipboardPanel(
        fake_input,
        clipboard,
        calibration=calibration,
        confirm_key="enter",
        timings=PanelTimings(0.0, 0.0, 0.0, 0.0),
        sleep=lambda _seconds: None,
    )
    panel.commit()
    assert game.last_confirm_key == "enter"


def test_missing_calibration_blocks_reading() -> None:
    panel, _game, _input = make_panel(calibration=Calibration.empty())
    with pytest.raises(PanelUnavailableError, match="Калибровку"):
        panel.read_pose()


def test_panel_is_unavailable_without_input_device() -> None:
    panel, _game, _input = make_panel(ready=False)
    assert not panel.is_available()


def test_commit_without_placeholder_is_refused() -> None:
    calibration = build_calibration()
    calibration = Calibration(fields=calibration.fields, placeholder=None)
    panel, _game, _input = make_panel(calibration=calibration)
    with pytest.raises(PanelUnavailableError, match="пустое место"):
        panel.commit()


def test_read_field_reports_garbage_instead_of_silently_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel, game, _input = make_panel()
    original = game.handle_combo

    def broken(combination: str) -> None:
        if combination == "ctrl+c":
            game.clipboard.text = "мусор"
        else:
            original(combination)

    monkeypatch.setattr(game, "handle_combo", broken)
    with pytest.raises(PanelUnavailableError, match="не число"):
        panel.read_field(FieldKey.X)
