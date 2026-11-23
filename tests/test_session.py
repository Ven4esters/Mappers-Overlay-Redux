"""Сессия: чтение панели, шаг и состояние."""

from __future__ import annotations

import math

import pytest
from map_overlay.application.session import MappingSession
from map_overlay.application.writer import PoseWriter
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.pose import Pose
from map_overlay.errors import (
    ApplicationError,
    NotCalibratedError,
    OperationCancelledError,
    PanelChangedError,
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


def test_forward_step_moves_x_plus_and_writes_x_only() -> None:
    panel = FakePanel(START)
    session = make_session(panel)
    session.capture()
    panel.writes.clear()
    result = session.step(Direction.FORWARD, 0.5)
    assert result.written == (Field.X,)
    assert panel.written_fields == [Field.X]
    assert result.pose.x == pytest.approx(START.x + 0.5)
    assert result.pose.y == pytest.approx(START.y)
    assert result.delta_x == pytest.approx(0.5)
    assert result.delta_y == pytest.approx(0.0)
    assert session.pose == result.pose


def test_diagonal_step_rotates_with_the_object() -> None:
    """``Num 3`` при наклоне 37°: поворот ``Y/Z``, ``X`` не меняется."""
    tilted = Pose(x=10.0, y=20.0, z=30.0, rx=37.0)
    panel = FakePanel(tilted)
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.BACK_RIGHT, 1.0)
    angle = math.radians(37.0)
    arm = 1.0 / math.sqrt(2.0)
    assert result.written == (Field.Y, Field.Z)
    assert result.pose.x == pytest.approx(10.0, abs=0.001)
    # ``Num 3`` — левая пара: у неё ``cos`` у ``Y`` и ``sin`` у ``Z``.
    assert result.pose.y == pytest.approx(20.0 - arm * math.cos(angle), abs=0.001)
    assert result.pose.z == pytest.approx(30.0 - arm * math.sin(angle), abs=0.001)


def test_diagonal_step_follows_rx_and_ry() -> None:
    """``RX = 55°`` и ``RY = 17°``: пишутся все три координаты, шаг длиной 3 м."""
    tilted = Pose(x=-1849.342, y=416.528, z=128.826, rx=55.0, ry=17.0)
    panel = FakePanel(tilted)
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.FORWARD_RIGHT, 3.0)
    assert result.written == (Field.X, Field.Y, Field.Z)
    assert result.pose.x == pytest.approx(-1848.465, abs=0.002)
    assert result.pose.y == pytest.approx(414.178, abs=0.002)
    assert result.pose.z == pytest.approx(130.472, abs=0.002)
    assert panel.written_fields == [Field.X, Field.Y, Field.Z]


def test_diagonal_step_without_tilt_is_forty_five_degrees() -> None:
    """Без наклона диагональ идёт 45° в плоскости экрана: пишутся ``Y`` и ``Z``."""
    panel = FakePanel(Pose(x=10.0, y=20.0, z=30.0))
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.FORWARD_RIGHT, 1.0)
    arm = 1.0 / math.sqrt(2.0)
    assert result.written == (Field.Y, Field.Z)
    assert result.pose.x == pytest.approx(10.0, abs=0.0005)
    assert result.pose.y == pytest.approx(20.0 - arm, abs=0.001)
    assert result.pose.z == pytest.approx(30.0 + arm, abs=0.001)


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


def test_confirm_requires_empty_point() -> None:
    panel = FakePanel(START)
    panel.has_empty_point = False
    with pytest.raises(NotCalibratedError, match="пустое место"):
        make_session(panel).confirm()


def test_confirm_presses_f_without_reading() -> None:
    panel = FakePanel(START)
    session = make_session(panel)
    session.confirm()
    assert panel.confirm_calls == 1
    assert panel.reads == []
    assert panel.writes == []


def test_failed_write_drops_the_pose() -> None:
    """После отказа панели координаты забываются: иначе шаг шёл бы от неверных."""
    panel = FakePanel(START)
    panel.reject.add(Field.X)
    session = make_session(panel)
    session.capture()
    with pytest.raises(PanelRejectedError):
        session.step(Direction.FORWARD, 0.5)
    assert session.pose is None
    with pytest.raises(PoseNotCapturedError):
        session.step(Direction.FORWARD, 0.5)


def test_tilted_step_writes_height_and_marks_result() -> None:
    """Режим высоты: ``Num 8`` пишет только ``Z``, ``X`` и ``Y`` остаются."""
    tilted = Pose(x=10.0, y=20.0, z=30.0, rx=30.0)
    panel = FakePanel(tilted)
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.FORWARD, 1.0, tilt=True)
    assert panel.pose().z == pytest.approx(31.0, abs=0.001)
    assert panel.pose().y == pytest.approx(20.0, abs=0.001)
    assert panel.pose().x == pytest.approx(10.0, abs=0.001)
    assert result.written == (Field.Z,)
    assert result.tilted is True
    assert result.delta_z == pytest.approx(1.0, abs=0.001)


def test_tilted_step_follows_ry() -> None:
    """При ``RY = 18°`` режим высоты пишет ``X`` и ``Z``, ``Y`` остаётся."""
    tilted = Pose(x=10.0, y=20.0, z=30.0, ry=18.0)
    panel = FakePanel(tilted)
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.FORWARD, 2.0, tilt=True)
    angle = math.radians(18.0)
    assert result.written == (Field.X, Field.Z)
    assert result.pose.x == pytest.approx(10.0 + 2.0 * math.sin(angle), abs=0.001)
    assert result.pose.y == pytest.approx(20.0, abs=0.001)
    assert result.pose.z == pytest.approx(30.0 + 2.0 * math.cos(angle), abs=0.001)


def test_alt_mode_keeps_the_diagonal_step() -> None:
    """Диагональ в режиме высоты идёт как обычно: ``RX``/``RY``, без подмены на ``Z``."""
    tilted = Pose(x=10.0, y=20.0, z=30.0, rx=30.0)
    panel = FakePanel(tilted)
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.FORWARD_LEFT, 1.0, tilt=True)
    arm = 1.0 / math.sqrt(2.0)
    assert result.written == (Field.Y, Field.Z)
    assert panel.pose().x == pytest.approx(10.0, abs=0.001)
    assert panel.pose().y == pytest.approx(20.0 + arm * math.cos(math.radians(30.0)), abs=0.001)


def test_plain_step_keeps_height() -> None:
    tilted = Pose(x=10.0, y=20.0, z=30.0, rx=30.0)
    panel = FakePanel(tilted)
    session = make_session(panel)
    session.capture()
    result = session.step(Direction.FORWARD, 1.0)
    assert Field.Z not in result.written
    assert result.delta_z == 0.0


def test_step_refuses_when_the_panel_was_changed() -> None:
    """Значение вписали руками — шаг не выполняется, координаты забыты."""
    panel = FakePanel(START)
    session = make_session(panel)
    session.capture()
    panel.values[Field.X] = "-1840.000"
    with pytest.raises(PanelChangedError, match="значение изменили"):
        session.step(Direction.FORWARD, 0.5)
    assert panel.writes == []
    assert session.pose is None


def test_cancelled_step_forgets_the_pose() -> None:
    """Прерванный шаг не оставляет «полуприменённых» координат."""
    panel = FakePanel(START)
    panel.cancel_after_writes = 1
    session = make_session(panel)
    session.capture()
    with pytest.raises(OperationCancelledError):
        session.step(Direction.FORWARD_RIGHT, 1.0)
    assert session.pose is None


def test_capture_can_be_cancelled() -> None:
    class CancellingPanel(FakePanel):
        def read_field(self, field: Field) -> str:
            self.cancel()
            return super().read_field(field)

    session = make_session(CancellingPanel(START))
    with pytest.raises(OperationCancelledError):
        session.capture()
    assert session.pose is None


def test_new_action_after_cancel_works() -> None:
    """Отмена не залипает: следующий «Считать» проходит как обычно."""
    panel = FakePanel(START)
    session = make_session(panel)
    session.cancel()
    assert session.capture().x == pytest.approx(START.x)


def test_failed_capture_forgets_the_old_pose() -> None:
    """Недочитанная панель: старые координаты не должны пережить сбой."""
    panel = FakePanel(START)
    session = make_session(panel)
    session.capture()
    panel.bad_read.add(Field.RZ)
    with pytest.raises(ApplicationError):
        session.capture()
    assert session.pose is None
