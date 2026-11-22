"""Диагностика «доходит ли ввод до игры» и повтор вставки."""

from __future__ import annotations

import pytest
from lsp_overlay.application.diagnostics import run_diagnostics
from lsp_overlay.application.writer import FieldWriter
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.pose import Pose

from fakes import FakeGamePanel

POSE = Pose(x=250.5, y=-810.25, z=31.0)


def test_healthy_panel_passes_diagnostics() -> None:
    panel = FakeGamePanel(POSE)
    report = run_diagnostics(panel)
    assert report.read_ok and report.write_ok
    assert "Ввод работает" in report.message


def test_unavailable_panel_explains_calibration() -> None:
    report = run_diagnostics(FakeGamePanel(POSE, available=False))
    assert not report.all_ok
    assert "Панель недоступна" in report.message


def test_unreadable_field_mentions_scaling() -> None:
    panel = FakeGamePanel(POSE)
    panel.read_pose = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        __import__(
            "lsp_overlay.application.errors", fromlist=["PanelUnavailableError"]
        ).PanelUnavailableError("поле X прочитано как «» — это не число")
    )
    report = run_diagnostics(panel)
    assert not report.read_ok
    assert "не читается" in report.message


def test_write_failure_mentions_admin_rights() -> None:
    panel = FakeGamePanel(POSE)
    panel.ignore_fields = {FieldKey.X}
    report = run_diagnostics(panel)
    assert report.read_ok
    assert not report.write_ok
    assert "администратора" in report.message


def test_writer_retries_once_and_succeeds() -> None:
    panel = FakeGamePanel(POSE)
    panel.ignore_once_fields = {FieldKey.Y}
    writer = FieldWriter(panel, retries=1)
    result = writer.write(POSE, Pose(x=POSE.x, y=-809.25, z=POSE.z), [FieldKey.Y])
    assert result.verified
    assert panel.pose.y == pytest.approx(-809.25)


def test_writer_gives_up_after_retry() -> None:
    panel = FakeGamePanel(POSE)
    panel.ignore_fields = {FieldKey.Y}
    writer = FieldWriter(panel, retries=1)
    with pytest.raises(Exception, match="не приняла"):
        writer.write(POSE, Pose(x=POSE.x, y=-809.25, z=POSE.z), [FieldKey.Y])
    assert panel.pose.y == pytest.approx(POSE.y)
