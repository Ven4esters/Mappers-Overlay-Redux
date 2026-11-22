"""Сессия: чтение панели, шаг и состояние."""

from __future__ import annotations

import pytest
from map_overlay.application.session import MappingSession
from map_overlay.application.writer import PoseWriter
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.pose import Pose
from map_overlay.errors import (
    ApplicationError,
    NotCalibratedError,
    PanelRejectedError,
    PoseNotCapturedError,
    ValidationError,
)

from fakes import FakePanel

START = Pose(x=-1848.763, y=409.366, z=125.002, rx=0.0, ry=0.0, rz=0.0)


def make_session(panel: FakePanel, *, verify: bool = True) -> MappingSession:
    return MappingSession(panel, PoseWriter(panel, decimals=3, verify=verify))


def test_capture_reads_all_fields_in_panel_order() -> None:
    panel = FakePanel(START)
    session = make_session(panel)
    assert session.pose is None
    pose = session.capture()
    assert panel.reads == list(PANEL_ORDER)
    assert pose.x == pytest.approx(START.x)
    assert pose.z == pytest.approx(START.z)
    assert session.pose == pose


def test_capture_reports_field_with_garbage() -> None:
    panel = FakePanel(START)
    panel.bad_read.add(Field.RY)
    with pytest.raises(ApplicationError, match="RY"):
        make_session(panel).capture()


def test_capture_requires_calibration() -> None:
    panel = FakePanel(START, missing=(Field.X, Field.Y))
    with pytest.raises(NotCalibratedError, match="X, Y"):
        make_session(panel).capture()


def test_step_needs_capture() -> None:
    panel = FakePanel(START)
    with pytest.raises(PoseNotCapturedError):
        make_session(panel).step(Direction.FORWARD, 0.5)


def test_forward_step_moves_x_minus_and_writes_x_only() -> None:
    panel = FakePanel(START)
    session = make_session(panel)
    session.capture()
    panel.writes.clear()
    result = session.step(Direction.FORWARD, 0.5)
    assert result.written == (Field.X,)
    assert panel.written_fields == [Field.X]
    assert result.pose.x == pytest.approx(START.x - 0.5)
    assert result.pose.y == pytest.approx(START.y)
    assert result.delta_x == pytest.approx(-0.5)
    assert result.delta_y == pytest.approx(0.0)
    assert session.pose == result.pose


def test_diagonal_step_writes_both_axes() -> None:
    panel = FakePanel(START)
    session = make_session(panel)
    session.capture()
    panel.writes.clear()
    result = session.step(Direction.BACK_RIGHT, 1.0)
    assert result.written == (Field.X, Field.Y)
    assert result.pose.x == pytest.approx(START.x + 1.0)
    assert result.pose.y == pytest.approx(START.y + 1.0)


def test_step_keeps_height_and_angles() -> None:
    panel = FakePanel(START)
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.LEFT, 0.25)
    assert result.pose.z == pytest.approx(START.z)
    assert (result.pose.rx, result.pose.ry, result.pose.rz) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("step", [0.0, -1.0, 1000.0])
def test_step_is_validated(step: float) -> None:
    panel = FakePanel(START)
    session = make_session(panel)
    session.capture()
    with pytest.raises(ValidationError):
        session.step(Direction.FORWARD, step)


def test_failed_write_keeps_previous_pose() -> None:
    panel = FakePanel(START)
    panel.reject.add(Field.X)
    session = make_session(panel)
    session.capture()
    with pytest.raises(PanelRejectedError):
        session.step(Direction.FORWARD, 0.5)
    assert session.pose == START
