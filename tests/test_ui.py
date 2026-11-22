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


def test_forward_arrow_moves_x_plus(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.arrow(Direction.FORWARD).click()
    assert panel.written_fields == [Field.X]
    assert panel.pose().x == pytest.approx(START.x + 0.5)
    assert "ΔX +0.500" in window.status_text()
    assert "записано: X" in window.status_text()


def test_diagonal_arrow_writes_two_fields(qt_app: QApplication) -> None:
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.arrow(Direction.BACK_RIGHT).click()
    component = 0.5 / 2**0.5
    assert panel.written_fields == [Field.X, Field.Y]
    assert panel.pose().x == pytest.approx(START.x - component, abs=0.001)
    assert panel.pose().y == pytest.approx(START.y - component, abs=0.001)


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


VK_MENU = 0x12
NUMPAD0 = 0x60
NUMPAD2 = 0x62
NUMPAD4 = 0x64
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
    assert panel.pose().x == pytest.approx(START.x + 0.5)


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


@pytest.mark.parametrize(
    ("vk", "expected_dx", "expected_dy"),
    [
        (0x68, 0.5, 0.0),  # Num 8 — вперёд
        (0x62, -0.5, 0.0),  # Num 2 — назад
        (0x64, 0.0, 0.5),  # Num 4 — влево
        (0x66, 0.0, -0.5),  # Num 6 — вправо
    ],
)
def test_numpad_directions_match_the_game(
    qt_app: QApplication, vk: int, expected_dx: float, expected_dy: float
) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(vk)
    hotkeys.release(vk)
    assert panel.pose().x == pytest.approx(START.x + expected_dx)
    assert panel.pose().y == pytest.approx(START.y + expected_dy)


@pytest.mark.parametrize(
    ("vk", "expected_dx", "expected_dy"),
    [
        (0x67, 0.354, 0.354),  # Num 7 — вперёд-влево
        (0x69, 0.354, -0.354),  # Num 9 — вперёд-вправо
        (0x61, -0.354, 0.354),  # Num 1 — назад-влево
        (0x63, -0.354, -0.354),  # Num 3 — назад-вправо
    ],
)
def test_numpad_diagonals_match_the_game(
    qt_app: QApplication, vk: int, expected_dx: float, expected_dy: float
) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(vk)
    hotkeys.release(vk)
    assert panel.pose().x == pytest.approx(START.x + expected_dx, abs=0.001)
    assert panel.pose().y == pytest.approx(START.y + expected_dy, abs=0.001)


# --- наклон по Alt ---------------------------------------------------------


def toggle_tilt(hotkeys: FakeHotkeySource) -> None:
    """Нажать Alt один раз, как это делает хук при одиночном нажатии."""
    hotkeys.press(VK_MENU)
    hotkeys.release(VK_MENU)


def test_alt_moves_forward_along_the_slope(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=30.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.pose().x == pytest.approx(START.x + 0.433, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z + 0.25, abs=0.001)
    assert panel.written_fields == [Field.X, Field.Z]
    assert "наклон" in window.status_text()


def test_alt_back_descends(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=30.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD2)
    hotkeys.release(NUMPAD2)
    assert panel.pose().z == pytest.approx(START.z - 0.25, abs=0.001)


def test_alt_sideways_keeps_the_height(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=30.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD4)
    hotkeys.release(NUMPAD4)
    assert panel.pose().y == pytest.approx(START.y + 0.5, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z, abs=0.001)
    assert panel.written_fields == [Field.Y]


def test_tilt_mode_with_flat_pose_is_a_plain_step(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.written_fields == [Field.X]


def test_alt_toggles_the_mode(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    assert window.movement.mode_text().startswith("Режим: по плоскости")
    toggle_tilt(hotkeys)
    assert window.movement.mode_text().startswith("Режим: по наклону")
    assert "Режим наклона включён" in window.status_text()
    toggle_tilt(hotkeys)
    assert window.movement.mode_text().startswith("Режим: по плоскости")
    assert "Режим наклона выключен" in window.status_text()


def test_tilt_mode_shows_the_angle(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=30.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    assert "RX 30.0" in window.movement.mode_text()


def test_tilt_mode_can_be_switched_during_the_hold(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=30.0)
    )
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    toggle_tilt(hotkeys)
    window._hold_tick()
    assert panel.pose().x == pytest.approx(START.x + 0.5 + 0.433, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z + 0.25, abs=0.001)


# --- удержание направления -------------------------------------------------


def test_hold_repeats_the_step_on_the_timer(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    assert window._hold_timer.isActive()
    for _ in range(4):
        window._hold_tick()
    assert panel.pose().x == pytest.approx(START.x + 2.5, abs=0.001)
    assert window._hold_timer.interval() == 150


def test_next_step_is_scheduled_right_after_the_previous_one(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    # Шаг завершился — следующий уже поставлен, паузы «до конца такта» нет.
    assert window._hold_timer.isActive()
    assert window._hold_timer.interval() == 150


def test_alt_held_still_turns_the_mode_on(qt_app: QApplication) -> None:
    """Привычка «Alt + направление» работает: режим включается, шаг идёт по наклону."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=30.0)
    )
    window.movement.press_capture()
    hotkeys.hold_alt()
    hotkeys.press(NUMPAD8)
    assert window.movement.mode_text().startswith("Режим: по наклону")
    assert panel.pose().z == pytest.approx(START.z + 0.25, abs=0.001)


def test_held_alt_is_reported_in_the_log(
    qt_app: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.hold_alt()
    with caplog.at_level("WARNING"):
        hotkeys.press(NUMPAD8)
    assert "Alt зажат" in caplog.text


def test_release_stops_the_hold(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert not window._hold_timer.isActive()
    window._hold_tick()
    assert panel.pose().x == pytest.approx(START.x + 0.5, abs=0.001)


def test_hold_stops_when_the_keyup_was_lost(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    hotkeys.forget(NUMPAD8)
    window._hold_tick()
    assert not window._hold_timer.isActive()
    assert panel.pose().x == pytest.approx(START.x + 0.5, abs=0.001)


def test_quick_tap_still_makes_the_step(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Клавишу отпустили раньше, чем окно обработало нажатие: шаг всё равно нужен."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    monkeypatch.setattr(hotkeys, "key_down", lambda _vk: False)
    hotkeys.press(NUMPAD8)
    assert panel.pose().x == pytest.approx(START.x + 0.5, abs=0.001)
    window._hold_tick()
    assert not window._hold_timer.isActive()
    assert panel.pose().x == pytest.approx(START.x + 0.5, abs=0.001)


def test_lost_release_does_not_kill_the_key(qt_app: QApplication) -> None:
    """Отпускание потерялось — следующее нажатие всё равно двигает предмет."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    hotkeys.forget(NUMPAD8)  # keyup до оверлея не дошёл
    hotkeys.press(NUMPAD8)
    assert panel.pose().x == pytest.approx(START.x + 1.0, abs=0.001)


def test_press_is_written_to_the_log(
    qt_app: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    with caplog.at_level("INFO"):
        hotkeys.press(NUMPAD8)
    assert "Клавиша Num 8" in caplog.text
    assert "Вперёд" in caplog.text


def test_step_without_capture_is_written_to_the_log(
    qt_app: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    with caplog.at_level("INFO"):
        hotkeys.press(NUMPAD8)
    assert "координаты не считаны" in caplog.text


def test_num_lock_timer_runs(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    assert window._num_lock_timer.isActive()


def test_num_lock_switched_off_is_reported(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    assert window.status_text() != ""
    hotkeys._num_lock = False  # пользователь выключил NumLock во время работы
    window._check_num_lock()
    assert "NumLock выключен" in window.status_text()


def test_num_lock_warning_is_not_repeated(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource(num_lock=False)
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window._set_status("прежний текст")
    window._check_num_lock()
    assert window.status_text() == "прежний текст"


def test_hold_waits_while_the_panel_is_busy(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    window._runner = _SlowRunner()  # type: ignore[assignment]
    hotkeys.press(NUMPAD8)
    window._hold_tick()
    assert panel.written_fields == []


def test_new_direction_replaces_the_held_one(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    hotkeys.press(NUMPAD4)
    window._hold_tick()
    assert panel.pose().y == pytest.approx(START.y + 1.0, abs=0.001)
    hotkeys.release(NUMPAD4)
    assert not window._hold_timer.isActive()


def test_hold_stops_when_hotkeys_are_paused(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    _hotkeys_checkbox(window).setChecked(False)
    assert not window._hold_timer.isActive()


def test_capture_stops_the_hold(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    window.movement.press_capture()
    assert not window._hold_timer.isActive()


class _AbandoningRunner:
    """Заглушка раннера, у которого есть что бросать."""

    def abandon(self) -> bool:
        return True


def test_abort_stops_the_hold(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    window._begin_busy("Шаг…")
    window._runner = _AbandoningRunner()  # type: ignore[assignment]
    window._abort_action()
    assert not window._hold_timer.isActive()
    assert "удержание остановлено" in window.status_text()


def test_hold_without_capture_does_not_loop(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    hotkeys.press(NUMPAD8)
    assert not window._hold_timer.isActive()
    assert "Сначала нажмите «Считать»" in window.status_text()
    assert panel.written_fields == []


def test_abort_button_is_enabled_only_while_busy(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    assert not window._abort_button.isEnabled()
    window._set_busy(True)
    assert window._abort_button.isEnabled()
    window._set_busy(False)
    assert not window._abort_button.isEnabled()


def test_heartbeat_timer_runs(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    assert window._heartbeat.isActive()


class _SlowRunner:
    """Заглушка занятого раннера для проверки счётчика времени."""

    def is_busy(self) -> bool:
        return True

    def busy_seconds(self) -> float:
        return 7.4


def test_busy_tick_hints_about_abort(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    window._begin_busy("Шаг вперёд…")
    assert "Шаг вперёд…" in window.status_text()
    window._runner = _SlowRunner()  # type: ignore[assignment]
    window._busy_tick()
    assert "(7 с)" in window.status_text()
    assert "Прервать" in window.status_text()


def test_abort_without_task_is_harmless(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    window._set_busy(True)
    window._abort_action()
    assert window._abort_button.isEnabled()
