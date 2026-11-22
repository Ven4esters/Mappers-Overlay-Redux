"""Интерфейс: вкладки, сценарии чтения и шага, калибровка, настройки."""

from __future__ import annotations

from dataclasses import replace

import pytest
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.actions import Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.errors import ValidationError
from map_overlay.ui.tabs.movement_tab import MovementTab
from map_overlay.ui.window import MainWindow
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QCheckBox

from fakes import FakeCursor, FakeHotkeySource, FakePanel, FakeStore

START = Pose(x=1850.0, y=1850.0, z=128.326, rx=0.0, ry=0.0, rz=0.0)


def make_window(
    qt_app: QApplication,
    *,
    pose: Pose = START,
    missing: tuple[Field, ...] = (),
    settings: Settings | None = None,
    hotkeys: FakeHotkeySource | None = None,
) -> tuple[MainWindow, FakePanel, FakeStore, FakeCursor]:
    panel = FakePanel(pose, missing=missing)
    store = FakeStore(settings)
    cursor = FakeCursor()
    context = AppContext(
        store=store,
        cursor=cursor,
        panel_factory=lambda _settings: panel,
        hotkeys=hotkeys or FakeHotkeySource(),
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
    component = 0.5 / 2**0.5
    assert panel.written_fields == [Field.X, Field.Y]
    assert panel.pose().x == pytest.approx(START.x + component, abs=0.001)
    assert panel.pose().y == pytest.approx(START.y + component, abs=0.001)


def test_tilt_warning_is_visible(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app, pose=replace(START, rx=5.0))
    window.movement.press_capture()
    assert "RX 5.000" in window.movement.warning_text()


def test_rz_alone_does_not_warn(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app, pose=replace(START, rz=20.0))
    window.movement.press_capture()
    assert window.movement.warning_text() == ""


def test_no_warning_for_flat_pose(qt_app: QApplication) -> None:
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
        hotkeys=FakeHotkeySource(),
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


NUMPAD0 = 0x60
NUMPAD5 = 0x65
NUMPAD8 = 0x68
F1 = 0x70
ESCAPE = 0x1B


def test_numpad_captures(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    hotkeys.press(NUMPAD0)
    hotkeys.release(NUMPAD0)
    assert panel.reads == list(Field)
    assert window.status_text().startswith("Считано")


def test_numpad_forward_moves_after_capture(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    hotkeys.press(NUMPAD0)
    hotkeys.release(NUMPAD0)
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.written_fields == [Field.X]
    assert panel.pose().x == pytest.approx(START.x - 0.5)


def test_held_key_moves_only_once(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    hotkeys.press(NUMPAD0)
    hotkeys.release(NUMPAD0)
    hotkeys.press(NUMPAD8)
    hotkeys.press(NUMPAD8)
    hotkeys.press(NUMPAD8)
    assert panel.written_fields == [Field.X]


def test_confirm_button_presses_f(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_confirm()
    assert panel.confirm_calls == 1
    assert "подтверждено" in window.status_text().lower()


def test_confirm_hotkey_presses_f(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    hotkeys.press(NUMPAD5)
    hotkeys.release(NUMPAD5)
    assert panel.confirm_calls == 1


def test_confirm_without_empty_point_is_explained(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    panel.has_empty_point = False
    window.movement.press_confirm()
    assert "пустое место" in window.status_text()
    assert panel.confirm_calls == 0


def test_empty_point_is_saved(qt_app: QApplication) -> None:
    window, _panel, store, cursor = make_window(qt_app)
    cursor.position = Point(55, 66)
    window.calibration.capture_empty_now()
    assert store.saved[-1].empty_point == Point(55, 66)
    assert "Точка пустого места сохранена" in window.status_text()


def test_num_lock_warning_is_shown(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=FakeHotkeySource(num_lock=False))
    assert "NumLock" in window.status_text()


def test_unavailable_hotkeys_are_reported(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=FakeHotkeySource(available=False))
    window.check_hotkey_state()
    assert "недоступны" in window.status_text()


def test_hotkey_can_be_rebound(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.settings_tab.hotkey_change_requested.emit(Action.CAPTURE)
    assert hotkeys.learning is True
    hotkeys.press(F1)
    assert store.saved[-1].hotkeys[Action.CAPTURE] == F1
    assert hotkeys.learning is False
    assert F1 in hotkeys.bound_keys
    assert "F1" in window.status_text()


def test_hotkey_learning_can_be_cancelled(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.settings_tab.hotkey_change_requested.emit(Action.CONFIRM)
    hotkeys.press(ESCAPE)
    assert store.saved == []
    assert hotkeys.learning is False
    assert "отменено" in window.status_text()


def test_hotkey_can_be_cleared(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.settings_tab.hotkey_clear_requested.emit(Action.CONFIRM)
    assert store.saved[-1].hotkeys[Action.CONFIRM] is None
    assert "снята" in window.status_text()


def _hotkeys_checkbox(window) -> QCheckBox:
    for box in window.settings_tab.findChildren(QCheckBox):
        if "Перехватывать" in box.text():
            return box
    raise AssertionError("галочка перехвата не найдена")


def test_window_does_not_take_focus_on_show(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_hotkeys_can_be_paused_and_resumed(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    box = _hotkeys_checkbox(window)
    box.setChecked(False)
    assert hotkeys.enabled is False
    assert "Перехват выключен" in window.status_text()
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.written_fields == []
    box.setChecked(True)
    assert hotkeys.enabled is True
    assert "Перехват клавиш включён" in window.status_text()


def test_paused_hotkeys_keep_buttons_working(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    _hotkeys_checkbox(window).setChecked(False)
    window.movement.press_confirm()
    assert panel.confirm_calls == 1


def test_learning_is_refused_while_paused(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    _hotkeys_checkbox(window).setChecked(False)
    window.settings_tab.hotkey_change_requested.emit(Action.CAPTURE)
    assert hotkeys.learning is False
    assert "нельзя" in window.status_text()


def test_learning_cancels_when_window_loses_focus(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.settings_tab.hotkey_change_requested.emit(Action.CONFIRM)
    assert hotkeys.learning is True
    window.changeEvent(QEvent(QEvent.Type.ActivationChange))
    assert hotkeys.learning is False
    assert store.saved == []
    assert "потеряло фокус" in window.status_text()


def test_learning_expires_by_timer(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.settings_tab.hotkey_change_requested.emit(Action.CONFIRM)
    window._learning_expired()
    assert hotkeys.learning is False
    assert store.saved == []
    assert "время вышло" in window.status_text()


def test_pausing_cancels_running_learning(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.settings_tab.hotkey_change_requested.emit(Action.CONFIRM)
    _hotkeys_checkbox(window).setChecked(False)
    assert hotkeys.learning is False
    assert "Перехват выключен" in window.status_text()


def test_hotkey_can_be_cleared_while_paused(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    _hotkeys_checkbox(window).setChecked(False)
    window.settings_tab.hotkey_clear_requested.emit(Action.CONFIRM)
    assert store.saved[-1].hotkeys[Action.CONFIRM] is None


def test_game_key_binding_warns_about_game_control(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.settings_tab.hotkey_change_requested.emit(Action.CAPTURE)
    hotkeys.press(0x57)  # W
    assert store.saved[-1].hotkeys[Action.CAPTURE] == 0x57
    assert "обычно занята" in window.status_text()
