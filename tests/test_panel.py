"""Автоматизация панели: порядок действий, паузы и защита мыши."""

from __future__ import annotations

import pytest
from map_overlay.config import Delays
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point
from map_overlay.errors import ClipboardError, NotCalibratedError
from map_overlay.infrastructure.panel import (
    MODIFIER_POLL_S,
    MODIFIER_WAIT_S,
    CalibratedPanel,
)

from fakes import FULL_CALIBRATION, FakeClipboard, FakeClock, FakeInput

VALUES = {field: f"{index}.000" for index, field in enumerate(Field)}


def make_panel(
    *,
    points: dict[Field, Point] | None = None,
    delays: Delays | None = None,
    empty_point: Point | None = None,
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
        empty_point=empty_point,
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


def test_exchange_waits_for_modifiers_to_be_released() -> None:
    """Зажатый Alt превратил бы ``Ctrl+A`` в ``Alt+Ctrl+A``: ждём отпускания."""
    panel, input_port, _clipboard, clock = make_panel()
    input_port.modifiers = 3
    text = panel.read_field(Field.X)
    assert text == VALUES[Field.X]
    assert clock.sleeps[:3] == [MODIFIER_POLL_S] * 3
    assert input_port.keys == ["ctrl+a", "ctrl+c"]


def test_modifier_wait_is_limited() -> None:
    """Если модификатор не отпускают, обмен всё равно идёт — но с предупреждением."""
    panel, input_port, _clipboard, clock = make_panel()
    input_port.modifiers = 1000
    panel.read_field(Field.X)
    assert len(clock.sleeps) <= int(MODIFIER_WAIT_S / MODIFIER_POLL_S) + 3


def test_custom_delays_are_used() -> None:
    delays = Delays(click=0.2, select=0.3, copy=0.4, paste=0.5)
    panel, _input_port, _clipboard, clock = make_panel(delays=delays)
    panel.read_field(Field.X)
    assert clock.sleeps == [0.2, 0.3, 0.4]


def test_read_field_fails_loudly_when_copy_did_not_arrive() -> None:
    """Если панель не получила ``Ctrl+C``, чтение не должно возвращать свой же буфер."""
    panel, input_port, _clipboard, _clock = make_panel()
    input_port.ignore_copy = True
    with pytest.raises(ClipboardError):
        panel.read_field(Field.X)


def test_read_field_clears_the_old_clipboard_before_copying() -> None:
    """Значение из прошлого обмена не должно выдаваться за прочитанное."""
    panel, input_port, clipboard, _clock = make_panel()
    clipboard.text = "999.999"
    input_port.ignore_copy = True
    with pytest.raises(ClipboardError):
        panel.read_field(Field.Y)


def test_missing_points_lists_uncalibrated_fields() -> None:
    panel, _input_port, _clipboard, _clock = make_panel(points={Field.X: FULL_CALIBRATION[Field.X]})
    assert panel.missing_points() == (Field.Y, Field.Z, Field.RX, Field.RY, Field.RZ)


def test_uncalibrated_field_cannot_be_used() -> None:
    panel, input_port, _clipboard, _clock = make_panel(points={})
    with pytest.raises(NotCalibratedError, match="X"):
        panel.read_field(Field.X)
    assert input_port.clicks == []


def test_cursor_drift_returns_to_the_field_and_continues() -> None:
    panel, input_port, _clipboard, _clock = make_panel()
    panel.read_field(Field.X)
    input_port.force_cursor(Point(900, 900))
    assert panel.read_field(Field.Y) == VALUES[Field.Y]
    assert input_port.clicked == [Field.X, Field.Y]
    assert input_port.clicks[-1] == FULL_CALIBRATION[Field.Y]
    assert input_port.cursor_position() == FULL_CALIBRATION[Field.Y]


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


def test_confirm_clicks_empty_spot_and_presses_f() -> None:
    empty = Point(900, 900)
    panel, input_port, _clipboard, clock = make_panel(empty_point=empty)
    assert panel.has_confirmation_point()
    panel.confirm()
    assert input_port.clicks == [empty]
    assert input_port.f_pressed == 1
    assert clock.sleeps == [Delays().click]


def test_confirm_without_point_is_refused() -> None:
    panel, input_port, _clipboard, _clock = make_panel()
    assert not panel.has_confirmation_point()
    with pytest.raises(NotCalibratedError, match="пустое место"):
        panel.confirm()
    assert input_port.f_pressed == 0


def test_confirm_after_cursor_drift_still_works() -> None:
    empty = Point(900, 900)
    panel, input_port, _clipboard, _clock = make_panel(empty_point=empty)
    panel.read_field(Field.X)
    input_port.force_cursor(Point(1, 1))
    panel.confirm()
    assert input_port.f_pressed == 1
    assert input_port.clicks[-1] == empty
