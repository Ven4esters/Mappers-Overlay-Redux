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


def test_focus_is_requested_before_typing_when_window_is_not_active() -> None:
    panel, game, fake_input = make_panel()
    fake_input.needs_activation = True
    panel.write_fields({FieldKey.X: 251.0})
    assert ("focus", "100,200") in fake_input.events
    assert game.pose.x == pytest.approx(251.0)


def test_focus_is_skipped_when_window_is_active() -> None:
    panel, _game, fake_input = make_panel()
    fake_input.needs_activation = False
    panel.write_fields({FieldKey.X: 251.0})
    assert not any(
        event[0] == "focus" and event[1].startswith("click") for event in fake_input.events
    )


def test_read_field_retries_when_clipboard_has_garbage() -> None:
    panel, game, _input = make_panel()
    game.clipboard.queue = ["Добро пожаловать, "]
    assert panel.read_field(FieldKey.X) == pytest.approx(POSE.x)


def test_read_field_gives_up_after_two_bad_attempts() -> None:
    panel, game, _input = make_panel()
    game.clipboard.queue = ["мусор", "мусор"]
    with pytest.raises(PanelUnavailableError, match="не число"):
        panel.read_field(FieldKey.X)


def test_tap_key_sends_configured_key() -> None:
    panel, _game, fake_input = make_panel()
    panel.tap_key("delete")
    assert ("key", "delete") in fake_input.events


def test_read_waits_until_clipboard_gets_the_value() -> None:
    panel, game, _input = make_panel()
    game.clipboard.lazy_polls = 3
    assert panel.read_field(FieldKey.Y) == pytest.approx(POSE.y)


def test_read_gives_up_when_clipboard_stays_stale() -> None:
    panel, game, _input = make_panel()
    game.clipboard.lazy_polls = 10_000
    with pytest.raises(PanelUnavailableError):
        panel.read_field(FieldKey.Y)


def test_mouse_drift_aborts_the_macro() -> None:
    panel, _game, fake_input = make_panel()
    fake_input.cursor_drift = (0, 0)
    with pytest.raises(PanelUnavailableError, match="курсор сдвинули"):
        panel.read_field(FieldKey.X)


def test_read_fields_reads_only_requested_keys() -> None:
    panel, _game, fake_input = make_panel()
    values = panel.read_fields((FieldKey.X,))
    assert values == {FieldKey.X: pytest.approx(POSE.x)}
    clicks = [event for event in fake_input.events if event[0] == "click"]
    assert len(clicks) == 1


def test_writer_verifies_only_written_fields() -> None:
    panel, _game, fake_input = make_panel()
    from lsp_overlay.application.writer import FieldWriter

    writer = FieldWriter(panel)
    before = panel.read_pose()
    fake_input.events.clear()
    target = before.translated((0.0, 1.0, 0.0))
    result = writer.write(before, target, (FieldKey.Y,))
    assert result.verified
    clicks = [event for event in fake_input.events if event[0] == "click"]
    # клик на запись поля + клик на проверку одного поля, а не вся панель
    assert len(clicks) == 2
