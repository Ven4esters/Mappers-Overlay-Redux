from __future__ import annotations

import pytest
from lsp_overlay.application.errors import ApplyError, PanelUnavailableError
from lsp_overlay.application.session import MappingSession
from lsp_overlay.application.writer import FieldWriter
from lsp_overlay.config import Settings
from lsp_overlay.domain.catalog import ObjectSpec
from lsp_overlay.domain.directions import DiagonalMode, Direction
from lsp_overlay.domain.errors import JumpTooLargeError
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.join import JoinRequest, JoinScheme, JoinSide
from lsp_overlay.domain.pose import Axis, Pose

from fakes import FakeGamePanel

PANEL_POSE = Pose(x=250.5, y=-810.25, z=31.0)


def make_session(pose: Pose = PANEL_POSE) -> tuple[MappingSession, FakeGamePanel]:
    panel = FakeGamePanel(pose)
    session = MappingSession(panel, Settings())
    session.capture()
    return session, panel


def test_capture_reads_panel_and_clears_changes() -> None:
    session, panel = make_session()
    assert session.pose == panel.pose
    assert session.pending_fields() == ()


def test_apply_without_capture_is_refused() -> None:
    panel = FakeGamePanel()
    session = MappingSession(panel, Settings())
    with pytest.raises(PanelUnavailableError, match="Считать"):
        session.apply()


def test_move_marks_only_changed_fields() -> None:
    session, _panel = make_session()
    session.move(Direction.NORTH, 1.0)
    assert session.pending_fields() == (FieldKey.Y,)


def test_rotated_move_changes_two_axes_at_once() -> None:
    session, _panel = make_session(Pose(rz=45.0))
    session.move(Direction.NORTH, 1.0)
    assert session.pending_fields() == (FieldKey.X, FieldKey.Y)


def test_apply_writes_changes_and_commits() -> None:
    session, panel = make_session()
    session.move(Direction.NORTH, 1.0)
    result = session.apply()
    assert result.verified
    assert panel.commits == 1
    assert panel.pose.y == pytest.approx(-809.25)
    assert session.pending_fields() == ()


def test_apply_without_commit_keeps_game_unsaved() -> None:
    session, panel = make_session()
    session.move(Direction.EAST, 0.5)
    session.apply(commit=False)
    assert panel.commits == 0


def test_apply_writes_nothing_when_nothing_changed() -> None:
    session, panel = make_session()
    result = session.apply()
    assert result.fields == ()
    assert panel.writes == []


def test_apply_does_not_press_f_when_nothing_changed() -> None:
    session, panel = make_session()
    result = session.apply(commit=True)
    assert result.fields == ()
    assert panel.commits == 0


def test_apply_skips_change_smaller_than_tolerance() -> None:
    session, panel = make_session()
    session.move(Direction.NORTH, 0.001)
    assert session.pending_fields() == (FieldKey.Y,)
    result = session.apply(commit=True)
    assert result.fields == ()
    assert panel.writes == []
    assert panel.commits == 0


def test_rotation_updates_only_angle_field() -> None:
    session, _panel = make_session()
    session.rotate(Axis.YAW, 10.0)
    assert session.pending_fields() == (FieldKey.RZ,)
    assert session.pose.rz == pytest.approx(10.0)


def test_manual_field_edit_is_pending() -> None:
    session, _panel = make_session()
    session.set_field(FieldKey.Z, 32.75)
    assert session.pending_fields() == (FieldKey.Z,)
    assert session.pose.z == pytest.approx(32.75)


def test_reset_to_panel_discards_changes() -> None:
    session, _panel = make_session()
    session.move(Direction.UP, 5.0)
    session.reset_to_panel()
    assert session.pending_fields() == ()


def test_jump_guard_blocks_huge_step() -> None:
    session, _panel = make_session()
    with pytest.raises(Exception, match="больше лимита"):
        session.move(Direction.UP, 50.0)


def test_diagonal_mode_from_settings_is_used() -> None:
    panel = FakeGamePanel()
    session = MappingSession(panel, Settings(diagonal_mode=DiagonalMode.SAME_STEP))
    session.capture()
    moved = session.move(Direction.NORTH_EAST, 1.0)
    assert moved.x == pytest.approx(1.0)
    assert moved.y == pytest.approx(1.0)


def test_writer_rolls_back_when_panel_ignores_paste() -> None:
    session, panel = make_session()
    panel.ignore_fields = {FieldKey.X}
    session.move(Direction.EAST, 1.0)
    with pytest.raises(ApplyError, match="не приняла") as error:
        session.apply()
    assert error.value.rolled_back
    assert session.pose.x == pytest.approx(251.5)  # желаемая поза не потеряна
    assert panel.pose.x == pytest.approx(250.5)  # в игре осталось прежнее


def test_writer_without_verification_does_not_read_back() -> None:
    panel = FakeGamePanel(Pose(x=1.0))
    writer = FieldWriter(panel, verify=False)
    result = writer.write(Pose(), Pose(x=2.0), [FieldKey.X])
    assert not result.verified
    assert panel.reads == 0


def test_writer_reports_unavailable_panel() -> None:
    panel = FakeGamePanel(available=False)
    writer = FieldWriter(panel)
    with pytest.raises(PanelUnavailableError):
        writer.write(Pose(), Pose(x=1.0), [FieldKey.X])


def test_writer_commit_propagates_panel_errors() -> None:
    session, panel = make_session()
    panel.available = False
    with pytest.raises(PanelUnavailableError):
        session.apply()


def test_movement_respects_prop_yaw() -> None:
    session, _panel = make_session(Pose(x=0.0, y=0.0, rz=90.0))
    moved = session.move(Direction.NORTH, 1.0)
    assert moved.x == pytest.approx(-1.0)
    assert moved.y == pytest.approx(0.0)


def test_place_join_writes_second_object_without_confirming() -> None:
    session, panel = make_session()
    wall = ObjectSpec(name="Стена", length=4.0, width=0.2, height=3.0)
    result = session.place_join(wall, wall, JoinRequest())
    assert result.fields
    assert panel.commits == 0
    assert panel.pose.x == pytest.approx(PANEL_POSE.x + 2.1)
    assert panel.pose.y == pytest.approx(PANEL_POSE.y + 1.9)
    assert panel.pose.z == pytest.approx(PANEL_POSE.z)
    assert session.pending_fields() == ()


def test_place_join_can_be_chained_into_a_corner() -> None:
    session, panel = make_session()
    wall = ObjectSpec(name="Стена", length=4.0, width=0.2, height=3.0)
    first = session.place_join(wall, wall, JoinRequest(scheme=JoinScheme.CORNER))
    second = session.place_join(
        wall, wall, JoinRequest(scheme=JoinScheme.CORNER, side=JoinSide.LEFT)
    )
    assert panel.pose.rz == pytest.approx(0.0)
    assert panel.pose.x == pytest.approx(first.pose.x + 1.9)
    assert panel.pose.y == pytest.approx(first.pose.y + 2.1)
    assert second.verified


def test_place_join_needs_captured_panel() -> None:
    panel = FakeGamePanel()
    session = MappingSession(panel, Settings())
    wall = ObjectSpec(name="Стена", length=4.0, width=0.2, height=3.0)
    with pytest.raises(PanelUnavailableError, match="Считать"):
        session.place_join(wall, wall, JoinRequest())


def test_place_join_stops_too_long_jump() -> None:
    session, _panel = make_session()
    long_wall = ObjectSpec(name="Длинная", length=60.0, width=0.2, height=3.0)
    with pytest.raises(JumpTooLargeError):
        session.place_join(long_wall, long_wall, JoinRequest())
