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

from fakes import FakeGamePanel, build_calibration  # noqa: E402

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


def test_window_has_four_tabs(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert titles == ["Движение", "Повороты", "Калибровка", "Настройки"]


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
