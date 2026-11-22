"""Дымовые тесты интерфейса: окно собирается и кнопки делают то, что обещают."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", reason="PySide6 недоступен")

from lsp_overlay.application.session import MappingSession  # noqa: E402
from lsp_overlay.config import Settings  # noqa: E402
from lsp_overlay.domain.directions import Direction  # noqa: E402
from lsp_overlay.domain.fields import FieldKey  # noqa: E402
from lsp_overlay.domain.pose import Pose  # noqa: E402
from lsp_overlay.infrastructure.config_store import ConfigStore  # noqa: E402
from lsp_overlay.ui.overlay import OverlayWindow  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from fakes import FakeGamePanel, build_calibration  # noqa: E402
from test_keymap import press_key  # noqa: E402

START = Pose(x=250.5, y=-810.25, z=31.0, rz=0.0)


def make_window(
    tmp_path: Path, qt_app: object, *, pose: Pose = START
) -> tuple[OverlayWindow, FakeGamePanel]:
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(pose)
    panel.configure(
        calibration=settings.calibration,
        timings=settings.timings,
        length_decimals=settings.length_decimals,
        confirm_key=settings.confirm_key,
    )
    session = MappingSession(panel, settings)
    window = OverlayWindow(session, ConfigStore(tmp_path / "settings.json"), settings)
    window.action_capture()
    return window, panel


def test_window_has_five_tabs(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert titles == ["Движение", "Повороты", "Рулетка", "Калибровка", "Настройки"]


def test_capture_fills_coordinate_editors(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    assert window.movement_tab.editors[FieldKey.X].value() == pytest.approx(250.5)
    assert window.movement_tab.editors[FieldKey.RZ].value() == pytest.approx(0.0)


def test_move_button_updates_pose_and_marks_pending(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    assert window.movement_tab.editors[FieldKey.Y].value() == pytest.approx(-809.25)
    assert window.btn_apply.isEnabled()


def test_arrow_pad_has_exactly_eight_directions(tmp_path: Path, qt_app: object) -> None:
    """В крестовине только план: 8 направлений, кнопок высоты нет."""
    from PySide6.QtWidgets import QPushButton

    window, _panel = make_window(tmp_path, qt_app)
    buttons = [
        button
        for button in window.movement_tab.findChildren(QPushButton)
        if button.objectName() == "arrowButton"
    ]
    assert len(buttons) == 8
    labels = {button.text() for button in buttons}
    assert labels == {"↖", "↑", "↗", "←", "→", "↙", "↓", "↘"}


def test_apply_writes_to_game_and_commits(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 0.5)
    window.action_apply(commit=True)
    assert panel.pose.y == pytest.approx(-809.75)
    assert panel.commits == 1
    assert "Записано" in window.lbl_status.text()


def test_jump_guard_reports_error(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_move(Direction.SOUTH.value, 100.0)
    assert window.lbl_status.property("level") == "error"
    assert "лимита" in window.lbl_status.text()


def test_rotate_tab_turns_yaw(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.rotate_tab.rotate_requested.emit("rz", 90.0)
    assert window.movement_tab.editors[FieldKey.RZ].value() == pytest.approx(90.0)


def test_calibration_tab_shows_points(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.calibration_tab.set_calibration(build_calibration())
    assert window.calibration_tab.lbl_placeholder.text() == "900, 900"
    assert window.calibration_tab.calibration.is_complete


def test_mini_mode_hides_tabs(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.btn_mini.click()
    assert window.tabs.isHidden()
    window.btn_mini.click()
    assert not window.tabs.isHidden()


def test_settings_saved_applies_opacity_and_persists(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    settings = Settings(calibration=build_calibration(), confirm_key="f", overlay_opacity=1.0)
    window.action_settings_saved(settings)
    assert window.windowOpacity() == pytest.approx(1.0)
    assert (tmp_path / "settings.json").exists()


def test_apply_without_capture_shows_error(tmp_path: Path, qt_app: object) -> None:
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(START)
    window = OverlayWindow(
        MappingSession(panel, settings), ConfigStore(tmp_path / "s.json"), settings
    )
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    window.action_apply(commit=True)
    assert "Считать" in window.lbl_status.text()


def test_height_is_editable_through_z_field(tmp_path: Path, qt_app: object) -> None:
    """Кнопок высоты нет, но Z по-прежнему можно задать вручную."""
    window, panel = make_window(tmp_path, qt_app)
    window.action_field_edited(FieldKey.Z.value, 31.75)
    window.action_apply(commit=True)
    assert panel.pose.z == pytest.approx(31.75)


def test_diagnostics_reports_success(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.calibration_tab.diagnostics_requested.emit()
    assert window.lbl_status.property("level") == "success"
    assert "Ввод работает" in window.lbl_status.text()


def test_diagnostics_reports_broken_write(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    panel.ignore_fields = {FieldKey.X}
    window.action_diagnostics()
    assert window.lbl_status.property("level") == "error"
    assert "администратора" in window.lbl_status.text()


def test_measure_tab_shows_object_length(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    assert window.measure_tab.value_text("distance") == "—"
    window.movement_tab.field_edited.emit(FieldKey.X.value, START.x + 4.5)
    window.action_remember_point("b")
    assert window.measure_tab.value_text("planar") == "4.500 м"
    assert window.measure_tab.value_text("heading") == "90.0°"


def test_measure_step_becomes_shift_step(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.Y.value, START.y + 2.0)
    window.action_remember_point("b")
    window.measure_tab.step_requested.emit(2.0)
    assert window.movement_tab.current_step() == pytest.approx(2.0)
    assert window._settings.step == pytest.approx(2.0)


def test_measure_reset_clears_points(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    window.measure_tab.reset_requested.emit()
    assert window.measure_tab.point_text("a") == "—"


def test_measure_step_button_waits_for_two_points(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    assert not window.measure_tab.btn_step.isEnabled()
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.X.value, START.x + 3.0)
    window.action_remember_point("b")
    assert window.measure_tab.btn_step.isEnabled()


def test_measure_copy_puts_text_on_clipboard(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.X.value, START.x + 1.0)
    window.action_remember_point("b")
    window.measure_tab.btn_copy.click()
    assert "Замер" in window.measure_tab.result_text()
    assert QGuiApplication.clipboard().text() == window.measure_tab.result_text()


def test_numpad_moves_prop_forward(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    assert window._session.pose.y == pytest.approx(START.y + 0.1)
    assert window._session.pending_fields() == (FieldKey.Y,)


def test_numpad_diagonal_moves_two_axes(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_9)
    half = 0.1 / 2**0.5
    assert window._session.pose.x == pytest.approx(START.x + half)
    assert window._session.pose.y == pytest.approx(START.y + half)


def test_numpad_five_saves_changes(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_6)
    press_key(window, Qt.Key.Key_5)
    assert panel.pose.x == pytest.approx(START.x + 0.1)
    assert panel.commits == 1


def test_numpad_enter_applies_without_confirm(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_6)
    press_key(window, Qt.Key.Key_Enter)
    assert panel.pose.x == pytest.approx(START.x + 0.1)
    assert panel.commits == 0


def test_numpad_plus_doubles_step(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_Plus)
    assert window.movement_tab.current_step() == pytest.approx(0.2)


def test_plain_arrow_does_nothing(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8, Qt.KeyboardModifier.NoModifier)
    assert window._session.pending_fields() == ()
