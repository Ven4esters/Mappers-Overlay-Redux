"""Запись полей: только отличия, повторы и понятные ошибки."""

from __future__ import annotations

from dataclasses import replace

import pytest
from map_overlay.application.writer import PoseWriter
from map_overlay.domain.fields import Field
from map_overlay.domain.pose import Pose
from map_overlay.errors import PanelRejectedError

from fakes import FakePanel

START = Pose(x=1850.0, y=1850.0, z=100.0, rx=0.0, ry=0.0, rz=0.0)


def make_writer(panel: FakePanel, *, verify: bool = True, decimals: int = 3) -> PoseWriter:
    return PoseWriter(panel, decimals=decimals, verify=verify)


def test_only_changed_fields_are_written() -> None:
    panel = FakePanel(START)
    writer = make_writer(panel)
    written = writer.write_changes(START, replace(START, x=1849.5))
    assert written == (Field.X,)
    assert panel.writes == [(Field.X, "1849.500")]
    assert panel.reads == [Field.X]


def test_nothing_changes_nothing_written() -> None:
    panel = FakePanel(START)
    assert make_writer(panel).write_changes(START, START) == ()
    assert panel.writes == []


def test_verification_can_be_disabled() -> None:
    panel = FakePanel(START)
    written = make_writer(panel, verify=False).write_changes(START, replace(START, x=1849.0))
    assert written == (Field.X,)
    assert panel.reads == []


def test_two_fields_for_diagonal() -> None:
    panel = FakePanel(START)
    written = make_writer(panel).write_changes(START, replace(START, x=1849.0, y=1849.0))
    assert written == (Field.X, Field.Y)
    assert panel.written_fields == [Field.X, Field.Y]


def test_rejected_write_is_retried_once() -> None:
    panelled = {Field.X: 1}

    class FlakyPanel(FakePanel):
        def write_field(self, field: Field, text: str) -> None:
            if panelled.get(field, 0) > 0:
                panelled[field] -= 1
                self.writes.append((field, text))
                return
            super().write_field(field, text)

    flaky = FlakyPanel(START)
    written = make_writer(flaky).write_changes(START, replace(START, x=1849.0))
    assert written == (Field.X,)
    assert flaky.written_fields == [Field.X, Field.X]


def test_rejected_write_reports_expected_and_actual() -> None:
    panel = FakePanel(START)
    panel.reject.add(Field.Y)
    with pytest.raises(PanelRejectedError) as error:
        make_writer(panel).write_changes(START, replace(START, y=1849.5))
    message = str(error.value)
    assert "Y" in message
    assert "1849.500" in message
    assert "1850.000" in message


def test_unreadable_field_is_reported() -> None:
    panel = FakePanel(START)
    panel.bad_read.add(Field.Z)
    with pytest.raises(PanelRejectedError, match="Z"):
        make_writer(panel).write_changes(START, replace(START, z=99.0))


def test_decimals_from_settings_are_used() -> None:
    panel = FakePanel(START)
    make_writer(panel, decimals=2).write_changes(START, replace(START, x=1849.0))
    assert panel.writes == [(Field.X, "1849.00")]
