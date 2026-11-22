"""Рулетка: расстояние между замерами и шаг для стыковки."""

from __future__ import annotations

import pytest
from lsp_overlay.application.session import MappingSession
from lsp_overlay.config import Settings
from lsp_overlay.domain.catalog import Dimension
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.measure import MeasureSlot, MeasureTape, Span
from lsp_overlay.domain.pose import Pose

from fakes import FakeGamePanel

START = Pose(x=100.0, y=200.0, z=30.0)
OBSTACLE_LENGTH = 4.5


def test_span_measures_straight_distance() -> None:
    span = Span.between(START, Pose(x=103.0, y=204.0, z=30.0))
    assert span.distance == pytest.approx(5.0)
    assert span.planar == pytest.approx(5.0)
    assert span.vertical == pytest.approx(0.0)


def test_span_keeps_vertical_part_apart() -> None:
    span = Span.between(START, Pose(x=100.0, y=200.0, z=32.5))
    assert span.planar == pytest.approx(0.0)
    assert span.vertical == pytest.approx(2.5)
    assert span.distance == pytest.approx(2.5)


def test_thickness_is_measured_vertically() -> None:
    span = Span.between(START, Pose(x=100.0, y=200.0, z=30.4))
    assert span.dimension_value(Dimension.THICKNESS, (0.0, 0.0, 0.0)) == pytest.approx(0.4)


def test_length_and_width_are_measured_along_own_axes() -> None:
    span = Span.between(START, Pose(x=102.0, y=204.0, z=30.0))
    assert span.dimension_value(Dimension.LENGTH, (0.0, 0.0, 0.0)) == pytest.approx(4.0)
    assert span.dimension_value(Dimension.WIDTH, (0.0, 0.0, 0.0)) == pytest.approx(2.0)


def test_heading_counts_clockwise_from_north() -> None:
    east = Span.between(START, Pose(x=START.x + 1.0, y=START.y, z=START.z))
    north = Span.between(START, Pose(x=START.x, y=START.y + 1.0, z=START.z))
    assert east.heading == pytest.approx(90.0)
    assert north.heading == pytest.approx(0.0)
    assert Span.between(START, START).heading == pytest.approx(0.0)


def test_span_reports_axis_projections() -> None:
    span = Span.between(START, Pose(x=101.5, y=196.5, z=31.0))
    assert [span.axis_span(index) for index in (0, 1, 2)] == pytest.approx([1.5, 3.5, 1.0])
    with pytest.raises(ValidationError):
        span.axis_span(3)


def test_degenerate_span_when_points_match() -> None:
    assert Span.between(START, START).is_degenerate
    assert not Span.between(START, Pose(x=START.x + 0.01, y=START.y, z=START.z)).is_degenerate


def test_step_uses_planar_length_and_falls_back_to_straight() -> None:
    planar = Span.between(START, Pose(x=START.x + OBSTACLE_LENGTH, y=START.y, z=START.z))
    assert planar.length_for_step() == pytest.approx(OBSTACLE_LENGTH)
    vertical = Span.between(START, Pose(x=START.x, y=START.y, z=START.z + 3.0))
    assert vertical.length_for_step() == pytest.approx(3.0)


def test_tape_needs_both_points() -> None:
    tape = MeasureTape()
    assert tape.span() is None
    tape.remember(MeasureSlot.FIRST, START)
    assert tape.span() is None
    tape.remember(MeasureSlot.SECOND, Pose(x=START.x + 2.0, y=START.y, z=START.z))
    span = tape.span()
    assert span is not None
    assert span.distance == pytest.approx(2.0)
    tape.clear()
    assert tape.points == {}


def test_tape_points_are_a_copy() -> None:
    tape = MeasureTape()
    tape.remember(MeasureSlot.FIRST, START)
    snapshot = tape.points
    snapshot.clear()
    assert tape.point(MeasureSlot.FIRST) == START


def test_session_measures_object_by_moving_the_prop() -> None:
    panel = FakeGamePanel(START)
    session = MappingSession(panel, Settings())
    session.capture()
    assert session.remember_point(MeasureSlot.FIRST) is None
    session.set_field(FieldKey.X, START.x + OBSTACLE_LENGTH)
    session.apply(commit=False)
    span = session.remember_point(MeasureSlot.SECOND)
    assert span is not None
    assert span.planar == pytest.approx(OBSTACLE_LENGTH)
    assert span.heading == pytest.approx(90.0)
    session.clear_tape()
    assert session.span is None
    assert session.tape_points() == {}
    assert panel.pose.x == pytest.approx(START.x + OBSTACLE_LENGTH)
