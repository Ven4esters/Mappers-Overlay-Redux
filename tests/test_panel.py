"""Автоматизация панели: порядок действий, паузы и защита мыши."""

from __future__ import annotations

import pytest
from map_overlay.config import Delays
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point
from map_overlay.errors import CursorMovedError, NotCalibratedError
from map_overlay.infrastructure.panel import CalibratedPanel

from fakes import FULL_CALIBRATION, FakeClipboard, FakeClock, FakeInput

VALUES = {field: f"{index}.000" for index, field in enumerate(Field)}


def make_panel(
    *,
    points: dict[Field, Point] | None = None,
    delays: Delays | None = None,
) -> tuple[CalibratedPanel, FakeInput, FakeClipboard, FakeClock]:
    clipboard = FakeClipboard()
    input_port = FakeInput(clipboard=clipboard, values=dict(VALUES), field_points=FULL_CALIBRATION)
    clock = FakeClock()
    panel = CalibratedPanel(
        input_port=input_port,
        clipboard=clipboard,
        clock=clock,
        points=FULL_CALIBRATION if points is None else points,
        delays=delays or Delays(),
    )
    return panel, input_port, clipboard, clock


def test_read_field_clicks_and_copies() -> None:
    panel, input_port, _clipboard, clock = make_panel()
    text = panel.read_field(Field.Y)
    assert text == VALUES[Field.Y]
    assert input_port.clicked == [Field.Y]
    assert input_port.keys == ["ctrl+a", "ctrl+c"]
    assert clock.sleeps == [Delays().click, Delays().select, Delays().copy]


def test_write_field_pastes_into_field() -> None:
    panel, input_port, clipboard, clock = make_panel()
    panel.write_field(Field.Z, "125.500")
    assert clipboard.text == "125.500"
    assert input_port.clicked == [Field.Z]
    assert input_port.keys == ["ctrl+a", "ctrl+v"]
    assert input_port.panel_value(Field.Z) == "125.500"
    assert clock.sleeps == [Delays().click, Delays().select, Delays().paste]


def test_custom_delays_are_used() -> None:
    delays = Delays(click=0.2, select=0.3, copy=0.4, paste=0.5)
    panel, _input_port, _clipboard, clock = make_panel(delays=delays)
    panel.read_field(Field.X)
    assert clock.sleeps == [0.2, 0.3, 0.4]


def test_missing_points_lists_uncalibrated_fields() -> None:
    panel, _input_port, _clipboard, _clock = make_panel(points={Field.X: FULL_CALIBRATION[Field.X]})
    assert panel.missing_points() == (Field.Y, Field.Z, Field.RX, Field.RY, Field.RZ)


def test_uncalibrated_field_cannot_be_used() -> None:
    panel, input_port, _clipboard, _clock = make_panel(points={})
    with pytest.raises(NotCalibratedError, match="X"):
        panel.read_field(Field.X)
    assert input_port.clicked == []


def test_cursor_drift_stops_the_exchange() -> None:
    panel, input_port, _clipboard, _clock = make_panel()
    panel.read_field(Field.X)
    input_port.force_cursor(Point(900, 900))
    with pytest.raises(CursorMovedError):
        panel.read_field(Field.Y)
    assert input_port.clicked == [Field.X]


def test_small_cursor_jitter_is_tolerated() -> None:
    panel, input_port, _clipboard, _clock = make_panel()
    panel.read_field(Field.X)
    point = FULL_CALIBRATION[Field.X]
    input_port.force_cursor(Point(point.x + 3, point.y - 2))
    assert panel.read_field(Field.Y) == VALUES[Field.Y]


def test_rejected_paste_leaves_value_unchanged() -> None:
    panel, input_port, _clipboard, _clock = make_panel()
    input_port.reject_paste.add(Field.RY)
    panel.write_field(Field.RY, "45.000")
    assert input_port.panel_value(Field.RY) == VALUES[Field.RY]
