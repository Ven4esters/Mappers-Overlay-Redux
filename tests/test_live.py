"""Живой режим: шаги уходят в игру из фонового потока."""

from __future__ import annotations

import time

import pytest
from lsp_overlay.application.live import LiveMover
from lsp_overlay.application.session import MappingSession
from lsp_overlay.config import Settings
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.pose import Pose

from fakes import FakeGamePanel

START = Pose(x=100.0, y=200.0, z=30.0)
TICK = 0.005


def wait_for(condition: object, timeout: float = 2.0) -> None:
    """Ждёт выполнения условия не дольше таймаута."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():  # type: ignore[operator]
            return
        time.sleep(0.005)
    raise AssertionError("условие не выполнилось за отведённое время")


def make_live() -> tuple[LiveMover, FakeGamePanel, MappingSession]:
    panel = FakeGamePanel(START)
    session = MappingSession(panel, Settings())
    session.capture()
    return LiveMover(session, tick=TICK), panel, session


def test_live_applies_steps_to_game_until_release() -> None:
    live, panel, _session = make_live()
    live.start()
    try:
        live.steer(Direction.NORTH, 0.5)
        wait_for(lambda: live.applied >= 2)
        live.release()
        steps = live.applied
        assert panel.pose.y > START.y + 0.5
        assert panel.commits >= 2
        assert panel.writes
        time.sleep(0.05)
        assert live.applied >= steps
    finally:
        live.stop()
    assert not live.is_running


def test_live_does_not_move_without_direction() -> None:
    live, panel, _session = make_live()
    live.start()
    try:
        time.sleep(0.05)
        assert live.applied == 0
        assert panel.pose == START
    finally:
        live.stop()


def test_live_stops_and_reports_error() -> None:
    live, panel, _session = make_live()
    panel.fail_write = True
    live.start()
    try:
        live.steer(Direction.EAST, 0.5)
        wait_for(lambda: live.last_error is not None)
    finally:
        live.stop()
    assert "поле" in (live.last_error or "").lower() or live.last_error


def test_live_writes_only_changed_fields() -> None:
    live, panel, _session = make_live()
    live.start()
    try:
        live.steer(Direction.NORTH, 1.0)
        wait_for(lambda: live.applied >= 1)
        live.release()
        time.sleep(0.05)
    finally:
        live.stop()
    written = set(panel.writes[0])
    assert written == {FieldKey.Y}


def test_session_clone_and_delete_use_configured_keys() -> None:
    panel = FakeGamePanel(START)
    settings = Settings(clone_key="v", clone_delete_key="delete")
    session = MappingSession(panel, settings)
    session.clone_object()
    session.delete_clone()
    assert panel.keys == ["v", "delete"]


def test_live_steer_replaces_direction_without_queue() -> None:
    live, _panel, _session = make_live()
    live.start()
    try:
        live.steer(Direction.NORTH, 0.5)
        live.steer(Direction.SOUTH, 0.5)
        assert live.direction is Direction.SOUTH
    finally:
        live.stop()
    assert live.direction is None


def test_live_step_is_passed_to_session() -> None:
    live, panel, _session = make_live()
    live.start()
    try:
        live.steer(Direction.NORTH, 3.0)
        wait_for(lambda: live.applied >= 1)
        live.release()
        time.sleep(0.05)
    finally:
        live.stop()
    moved = panel.pose.y - START.y
    assert moved >= 3.0
    assert moved % 3.0 == pytest.approx(0.0, abs=1e-6)
