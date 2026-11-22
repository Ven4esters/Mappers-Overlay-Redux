"""Интерфейс: вкладки, сценарии чтения и шага, калибровка, настройки."""

from __future__ import annotations

from dataclasses import replace

import pytest
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.errors import ValidationError
from map_overlay.ui.tabs.movement_tab import MovementTab
from map_overlay.ui.window import MainWindow
from PySide6.QtWidgets import QApplication

from fakes import FakeCursor, FakePanel, FakeStore

START = Pose(x=1850.0, y=1850.0, z=128.326, rx=0.0, ry=0.0, rz=0.0)


def make_window(
    qt_app: QApplication,
    *,
    pose: Pose = START,
    missing: tuple[Field, ...] = (),
    settings: Settings | None = None,
) -> tuple[MainWindow, FakePanel, FakeStore, FakeCursor]:
    panel = FakePanel(pose, missing=missing)
    store = FakeStore(settings)
    cursor = FakeCursor()
    context = AppContext(
        store=store,
        cursor=cursor,
        panel_factory=lambda _settings: panel,
        config_path=None,
    )
    window = MainWindow(context, synchronous_tasks=True)
    return window, panel, store, cursor


def test_three_tabs(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    assert window.tab_titles() == ["Движение", "Калибровка", "Настройки"]


def test_capture_shows_pose(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    assert window.status_text().startswith("Считано")
    assert panel.reads == list(Field)


def test_arrow_before_capture_asks_to_read(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.arrow(Direction.FORWARD).click()
    assert "Считать" in window.status_text()
    assert panel.writes == []


def test_forward_arrow_moves_x_minus(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.arrow(Direction.FORWARD).click()
    assert panel.written_fields == [Field.X]
    assert panel.pose().x == pytest.approx(START.x - 0.5)
    assert "ΔX -0.500" in window.status_text()
    assert "записано: X" in window.status_text()


def test_diagonal_arrow_writes_two_fields(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.arrow(Direction.BACK_RIGHT).click()
    assert panel.written_fields == [Field.X, Field.Y]
    assert panel.pose().x == pytest.approx(START.x + 0.5)
    assert panel.pose().y == pytest.approx(START.y + 0.5)


def test_rotation_warning_is_visible(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app, pose=replace(START, rz=20.0))
    window.movement.press_capture()
    assert "RZ 20.000" in window.movement.warning_text()


def test_no_warning_without_rotation(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    assert window.movement.warning_text() == ""


def test_rejected_write_is_shown(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    panel.reject.add(Field.X)
    window.movement.press_capture()
    window.movement.arrow(Direction.FORWARD).click()
    assert "Панель не приняла" in window.status_text()
    assert "X" in window.status_text()


def test_calibration_point_is_saved(qt_app: QApplication) -> None:
    window, _panel, store, cursor = make_window(qt_app)
    cursor.position = Point(640, 480)
    window.calibration.capture_now(Field.X)
    assert store.saved[-1].calibration == {Field.X: Point(640, 480)}
    assert "Не хватает полей" in window.status_text()


def test_settings_are_saved_and_session_reset(qt_app: QApplication) -> None:
    window, _panel, store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    new_settings = Settings(default_step=2.0, verify_writes=False)
    window.settings_tab.settings_saved.emit(new_settings)
    assert store.saved[-1] == new_settings
    assert "Нажмите «Считать» заново" in window.status_text()


def test_broken_settings_message(qt_app: QApplication) -> None:
    class BrokenStore(FakeStore):
        def load(self) -> Settings:
            from map_overlay.errors import ConfigError

            raise ConfigError("файл настроек испорчен")

    context = AppContext(
        store=BrokenStore(),
        cursor=FakeCursor(),
        panel_factory=lambda _settings: FakePanel(START),
        config_path=None,
    )
    window = MainWindow(context, synchronous_tasks=True)
    assert "испорчен" in window.status_text()


def test_step_field_is_validated(qt_app: QApplication) -> None:
    tab = MovementTab(default_step=0.5)
    tab._step_combo.setCurrentText("1000")
    with pytest.raises(ValidationError, match="Шаг"):
        tab.current_step()


def test_calibration_countdown_captures_point(qt_app: QApplication) -> None:
    from map_overlay.ui.tabs.calibration_tab import CalibrationTab

    cursor = FakeCursor(Point(700, 500))
    tab = CalibrationTab(cursor=cursor, points={}, countdown_seconds=0, tick_ms=0)
    tab.start_capture(Field.RZ)
    for _ in range(5):
        qt_app.processEvents()
    assert tab.points() == {Field.RZ: Point(700, 500)}


def test_show_point_moves_cursor(qt_app: QApplication) -> None:
    window, _panel, _store, cursor = make_window(qt_app)
    window.calibration.capture_now(Field.X)
    window.calibration.show_point(Field.X)
    assert Point(100, 200) in cursor.moved


def test_show_point_for_unknown_field_is_explained(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    window.calibration.show_point(Field.Y)
    assert "не откалибровано" in window.status_text()
