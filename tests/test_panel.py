"""Автоматизация панели: порядок действий, паузы и защита мыши."""

from __future__ import annotations

import pytest
from map_overlay.config import Delays
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point
from map_overlay.errors import ClipboardError, NotCalibratedError, OperationCancelledError
from map_overlay.infrastructure.panel import (
    MODIFIER_POLL_S,
    MODIFIER_WAIT_S,
    CalibratedPanel,
    PanelConfig,
)
from map_overlay.trace import JOURNAL

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
        input_port,
        clipboard,
        clock,
        PanelConfig(
            points=FULL_CALIBRATION if points is None else points,
            delays=delays or Delays(),
            empty_point=empty_point,
        ),
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
    # Буфер возвращается пользователю: в нём не остаётся координата.
    assert clipboard.text == ""
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


def test_read_field_is_logged_with_value() -> None:
    """В журнале действий видно, что именно прочитано и куда кликали."""
    panel, _input, _clipboard, _clock = make_panel()
    JOURNAL.clear()
    text = panel.read_field(Field.X)
    log = JOURNAL.describe()
    assert "начал: чтение поля X" in log
    assert "клик: X в" in log
    assert f"поле X прочитано: «{text.strip()}»" in log
    assert "готово: чтение поля X" in log


def test_write_field_is_logged_with_value() -> None:
    panel, _input, _clipboard, _clock = make_panel()
    JOURNAL.clear()
    panel.write_field(Field.Z, "42.500")
    log = JOURNAL.describe()
    assert "начал: запись поля Z = 42.500" in log
    assert "готово: запись поля Z = 42.500" in log


def test_confirm_is_logged() -> None:
    panel, _input, _clipboard, _clock = make_panel(empty_point=Point(x=5, y=5))
    JOURNAL.clear()
    panel.confirm()
    assert "нажать F в пустом месте панели" in JOURNAL.describe()


def test_modifier_wait_is_logged() -> None:
    panel, input_port, _clipboard, _clock = make_panel()
    input_port.modifiers = 2
    JOURNAL.clear()
    panel.read_field(Field.X)
    assert "ждал отпускания Alt/Ctrl/Shift" in JOURNAL.describe()


def test_read_field_returns_user_clipboard() -> None:
    """Скопированный пользователем текст не должен пропадать при чтении поля."""
    panel, _input, clipboard, _clock = make_panel()
    clipboard.text = "текст пользователя"
    text = panel.read_field(Field.X)
    assert text == VALUES[Field.X]
    assert clipboard.text == "текст пользователя"


def test_write_field_returns_user_clipboard() -> None:
    panel, _input, clipboard, _clock = make_panel()
    clipboard.text = "пароль из чужого окна"
    panel.write_field(Field.X, "10.000")
    assert clipboard.text == "пароль из чужого окна"


def test_clipboard_is_restored_when_field_is_empty() -> None:
    """Панель не отдала значение — буфер всё равно возвращается пользователю."""
    panel, input_port, clipboard, _clock = make_panel()
    clipboard.text = "пользователь"
    input_port.ignore_copy = True
    with pytest.raises(ClipboardError):
        panel.read_field(Field.X)
    assert clipboard.text == "пользователь"


def test_clipboard_is_restored_after_cancel() -> None:
    panel, _input, clipboard, _clock = make_panel()
    clipboard.text = "пользователь"
    panel.cancel()
    with pytest.raises(OperationCancelledError):
        panel.write_field(Field.X, "10.000")
    assert clipboard.text == "пользователь"


def test_step_survives_unavailable_clipboard() -> None:
    """Если буфер не читается, шаг не падает: вернуть будет нечего."""
    panel, input_port, clipboard, _clock = make_panel()
    clipboard.text = "пользователь"
    clipboard.fail_get = True
    panel.write_field(Field.X, "10.000")
    assert input_port.panel_value(Field.X) == "10.000"


def test_restore_failure_does_not_break_step() -> None:
    """Буфер заняли между обменом и восстановлением — шаг всё равно завершён."""

    class RestoreFails(FakeClipboard):
        def __init__(self, text: str) -> None:
            super().__init__(text)
            self.calls = 0

        def set(self, text: str) -> None:
            self.calls += 1
            if self.calls > 1:
                raise ClipboardError("буфер занят другим приложением")
            super().set(text)

    clipboard = RestoreFails("пользователь")
    input_port = FakeInput(clipboard=clipboard, values=dict(VALUES), field_points=FULL_CALIBRATION)
    panel = CalibratedPanel(
        input_port,
        clipboard,
        FakeClock(),
        PanelConfig(points=FULL_CALIBRATION, delays=Delays()),
    )
    panel.write_field(Field.X, "10.000")
    assert input_port.panel_value(Field.X) == "10.000"


def test_clipboard_restore_is_logged_without_content() -> None:
    panel, _input, clipboard, _clock = make_panel()
    clipboard.text = "секретный текст"
    JOURNAL.clear()
    panel.read_field(Field.X)
    log = JOURNAL.describe()
    assert "буфер обмена пользователя восстановлен" in log
    assert "секретный текст" not in log
