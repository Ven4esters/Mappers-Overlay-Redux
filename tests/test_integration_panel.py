"""Сквозные тесты: сессия + настоящая панель ввода поверх эмулятора LSP."""

from __future__ import annotations

import pytest
from lsp_overlay.application.errors import ApplyError
from lsp_overlay.application.session import MappingSession
from lsp_overlay.config import PanelTimings, Settings
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.movement import MoveFrame
from lsp_overlay.domain.pose import Axis, Pose
from lsp_overlay.infrastructure.panel import ClipboardPanel

from fakes import FakeClipboard, FakeInput, FakeLspGame, build_calibration

START = Pose(x=250.5, y=-810.25, z=31.0, rz=0.0)
AXIS_FIELD = FieldKey.RZ


def make_stack(
    *, drop_select_all: bool = False, frame: MoveFrame = MoveFrame.WORLD
) -> tuple[MappingSession, FakeLspGame]:
    calibration = build_calibration()
    clipboard = FakeClipboard()
    game = FakeLspGame(calibration, START, clipboard, drop_select_all=drop_select_all)
    fake_input = FakeInput(game)
    panel = ClipboardPanel(
        fake_input,
        clipboard,
        calibration=calibration,
        timings=PanelTimings(0.0, 0.0, 0.0, 0.0),
        sleep=lambda _seconds: None,
    )
    settings = Settings(timings=PanelTimings(0.0, 0.0, 0.0, 0.0), move_frame=frame)
    session = MappingSession(panel, settings)
    return session, game


def test_full_cycle_moves_prop_and_saves_with_f() -> None:
    session, game = make_stack()
    session.capture()
    session.move(Direction.NORTH, 1.0)
    result = session.apply()

    assert result.verified
    assert game.pose.y == pytest.approx(-809.25)
    assert game.commits == 1
    assert game.last_confirm_key == "f"


def test_rotated_prop_moves_along_its_own_axis() -> None:
    session, game = make_stack(frame=MoveFrame.PROP)
    session.capture()
    session.rotate(Axis.YAW, 90.0)
    session.apply()
    session.move(Direction.NORTH, 2.0)
    session.apply()

    assert game.pose.x == pytest.approx(250.5 - 2.0, abs=1e-3)
    assert game.pose.y == pytest.approx(-810.25, abs=1e-3)


def test_world_frame_ignores_prop_rotation() -> None:
    session, game = make_stack()
    session.capture()
    session.rotate(Axis.YAW, 90.0)
    session.apply()
    session.move(Direction.NORTH, 2.0)
    session.apply()

    assert game.pose.y == pytest.approx(-810.25 + 2.0, abs=1e-3)
    assert game.pose.x == pytest.approx(250.5, abs=1e-3)


def test_lost_select_all_is_caught_and_prop_stays_in_place() -> None:
    session, game = make_stack()
    session.capture()
    game.drop_select_all = True  # Ctrl+A перестал работать посреди работы
    session.move(Direction.UP, 1.0)

    with pytest.raises(ApplyError, match="Не удалось проверить"):
        session.apply()

    assert game.commits == 0  # сохранение не нажималось
    assert game.pose.z == pytest.approx(START.z, abs=1e-3)


def test_manual_angle_edit_is_written_as_plain_number() -> None:
    session, game = make_stack()
    session.capture()
    session.set_field(AXIS_FIELD, 37.5)
    session.apply()
    assert game.pose.rz == pytest.approx(37.5)
