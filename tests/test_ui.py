"""Интерфейс: вкладки, сценарии чтения и шага, калибровка, настройки."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from pathlib import Path

import pytest
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.actions import Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.movement import alt_hint
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.domain.sizes import ObjectSize, SizeLibrary, SizeUse
from map_overlay.errors import ValidationError
from map_overlay.infrastructure.size_store import JsonSizeStore
from map_overlay.trace import JOURNAL
from map_overlay.ui.tabs.movement_tab import MovementTab
from map_overlay.ui.window import MainWindow
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from fakes import (
    FULL_CALIBRATION,
    FakeCursor,
    FakeHotkeySource,
    FakePanel,
    FakeSizeStore,
    FakeStore,
)

START = Pose(x=1850.0, y=1850.0, z=128.326, rx=0.0, ry=0.0, rz=0.0)


def make_window(
    qt_app: QApplication,
    *,
    pose: Pose = START,
    missing: tuple[Field, ...] = (),
    settings: Settings | None = None,
    hotkeys: FakeHotkeySource | None = None,
    size_store: FakeSizeStore | None = None,
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
        size_store=size_store,
    )
    window = MainWindow(context, synchronous_tasks=True)
    return window, panel, store, cursor


def test_four_tabs(qt_app: QApplication) -> None:
    window, _panel, _store, _cursor = make_window(qt_app)
    assert window.tab_titles() == ["Навигация", "Размеры", "Калибровка", "Настройки"]


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


def test_diagonal_arrow_rotates_with_the_object(qt_app: QApplication) -> None:
    """Кнопка «назад-вправо» при наклоне 37° и ``RY = 0``: ``X`` на месте."""
    window, panel, _store, _cursor = make_window(qt_app, pose=replace(START, rx=37.0))
    window.movement.press_capture()
    window.movement.arrow(Direction.BACK_RIGHT).click()
    angle = math.radians(37.0)
    arm = 0.5 / math.sqrt(2.0)
    assert panel.written_fields == [Field.Y, Field.Z]
    assert panel.pose().x == pytest.approx(START.x, abs=0.001)
    # ``Num 3`` из левой пары: ``cos`` у ``Y``, ``sin`` у ``Z`` (эталоны 1.8.1).
    assert panel.pose().y == pytest.approx(START.y - arm * math.cos(angle), abs=0.001)
    assert panel.pose().z == pytest.approx(START.z - arm * math.sin(angle), abs=0.001)


def test_diagonal_arrow_follows_rx_and_ry(qt_app: QApplication) -> None:
    """Кнопка «вверх-вправо» при ``RX = 55°`` и ``RY = 17°``: пишутся ``X``, ``Y`` и ``Z``."""
    start = replace(START, x=-1849.342, y=416.528, z=128.826, rx=55.0, ry=17.0)
    window, panel, _store, _cursor = make_window(qt_app, pose=start)
    window.movement.press_capture()
    window.movement._step_combo.setCurrentText("3")
    window.movement.arrow(Direction.FORWARD_RIGHT).click()
    assert panel.written_fields == [Field.X, Field.Y, Field.Z]
    assert panel.pose().x == pytest.approx(-1848.465, abs=0.002)
    assert panel.pose().y == pytest.approx(414.178, abs=0.002)
    assert panel.pose().z == pytest.approx(130.472, abs=0.002)


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
NUMPAD6 = 0x66
NUMPAD7 = 0x67
NUMPAD8 = 0x68
NUMPAD9 = 0x69
NUMPAD1 = 0x61
NUMPAD3 = 0x63
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


QUARTER = 0.5 / 2**0.5  # плечо диагонали при шаге 0.5 м


@pytest.mark.parametrize(
    ("vk", "expected_dy", "expected_dz"),
    [
        (0x67, QUARTER, QUARTER),  # Num 7 — влево и вверх
        (0x69, -QUARTER, QUARTER),  # Num 9 — вправо и вверх
        (0x61, QUARTER, -QUARTER),  # Num 1 — влево и вниз
        (0x63, -QUARTER, -QUARTER),  # Num 3 — вправо и вниз
    ],
)
def test_numpad_diagonals_at_zero_are_forty_five_degrees(
    qt_app: QApplication, vk: int, expected_dy: float, expected_dz: float
) -> None:
    """При ``RX = 0`` диагональ идёт 45° в плоскости экрана: ``Y`` и ``Z``, ``X`` тот же."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(vk)
    hotkeys.release(vk)
    assert panel.pose().x == pytest.approx(START.x, abs=0.0005)
    assert panel.pose().y == pytest.approx(START.y + expected_dy, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z + expected_dz, abs=0.001)


def test_numpad_diagonal_at_37_rotates_the_step(qt_app: QApplication) -> None:
    """При наклоне 37° шаг поворачивается вместе с предметом (``P + Rx(RX)·Δ_local``)."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=37.0)
    )
    window.movement.press_capture()
    hotkeys.press(0x69)  # Num 9 — вверх-вправо
    hotkeys.release(0x69)
    assert panel.pose().x == pytest.approx(START.x, abs=0.002)
    assert panel.pose().y == pytest.approx(START.y - 0.213, abs=0.002)
    assert panel.pose().z == pytest.approx(START.z + 0.282, abs=0.002)


# --- режим по экрану (Alt) ------------------------------------------------


def toggle_tilt(hotkeys: FakeHotkeySource) -> None:
    """Нажать Alt один раз, как это делает хук при одиночном нажатии."""
    hotkeys.press(VK_MENU)
    hotkeys.release(VK_MENU)


def test_alt_forward_goes_up(qt_app: QApplication) -> None:
    """``Num 8`` в режиме высоты поднимает предмет: меняется только ``Z``."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=45.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.pose().x == pytest.approx(START.x, abs=0.001)
    assert panel.pose().y == pytest.approx(START.y, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z + 0.5, abs=0.001)
    assert panel.written_fields == [Field.Z]
    assert "Alt: вверх/вниз" in window.status_text()


def test_alt_back_goes_down(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=45.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD2)
    hotkeys.release(NUMPAD2)
    assert panel.pose().z == pytest.approx(START.z - 0.5, abs=0.001)
    assert panel.written_fields == [Field.Z]


def test_alt_forward_follows_ry(qt_app: QApplication) -> None:
    """При ``RY = 10°`` подъём идёт в плоскости ``X/Z``: пишутся ``X`` и ``Z``."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, ry=10.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.written_fields == [Field.X, Field.Z]
    assert panel.pose().x == pytest.approx(START.x + 0.5 * math.sin(math.radians(10.0)), abs=0.001)
    assert panel.pose().y == pytest.approx(START.y, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z + 0.5 * math.cos(math.radians(10.0)), abs=0.001)


def test_alt_keeps_left_and_right_as_they_were(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=45.0)
    )
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD4)
    hotkeys.release(NUMPAD4)
    assert panel.pose().y == pytest.approx(START.y + 0.5, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z, abs=0.001)


def test_alt_keeps_diagonals_working(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD9)
    hotkeys.release(NUMPAD9)
    assert panel.pose().x == pytest.approx(START.x, abs=0.0005)
    assert panel.pose().y == pytest.approx(START.y - QUARTER, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z + QUARTER, abs=0.001)


def test_alt_toggles_the_mode(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    assert window.movement.mode_text() == "8/2 — вперёд/назад"
    toggle_tilt(hotkeys)
    assert window.movement.mode_text() == alt_hint()
    assert "Режим высоты включён" in window.status_text()
    toggle_tilt(hotkeys)
    assert window.movement.mode_text() == "8/2 — вперёд/назад"
    assert "Режим высоты выключен" in window.status_text()


def test_pad_tooltips_show_the_alt_mode(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    forward = window.movement.arrow(Direction.FORWARD)
    back = window.movement.arrow(Direction.BACK)
    diagonal = window.movement.arrow(Direction.FORWARD_LEFT)
    assert "X +" in forward.toolTip()
    toggle_tilt(hotkeys)
    assert "вверх на шаг (Alt)" in forward.toolTip()
    assert "вниз на шаг (Alt)" in back.toolTip()
    assert "вверх-влево" in diagonal.toolTip()
    assert forward.text() == "\u2191"
    toggle_tilt(hotkeys)
    assert "X +" in forward.toolTip()


def test_tilt_checkbox_switches_the_mode(qt_app: QApplication) -> None:
    """Мышь тоже умеет: галочка на вкладке — тот же переключатель."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    box = window.movement._tilt_box
    box.click()
    assert window.movement.mode_text() == alt_hint()
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.pose().z == pytest.approx(START.z + 0.5, abs=0.001)
    box.click()
    assert window.movement.mode_text() == "8/2 — вперёд/назад"


def test_hotkey_toggle_updates_the_checkbox(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    toggle_tilt(hotkeys)
    assert window.movement._tilt_box.isChecked() is True
    toggle_tilt(hotkeys)
    assert window.movement._tilt_box.isChecked() is False


def test_tilt_mode_can_be_switched_during_the_hold(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    hotkeys.press(NUMPAD8)
    toggle_tilt(hotkeys)
    window._hold_tick()
    assert panel.pose().x == pytest.approx(START.x + 0.5, abs=0.001)
    assert panel.pose().z == pytest.approx(START.z + 0.5, abs=0.001)


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
    """Привычка «Alt + направление» работает: режим включается, шаг как обычно."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(
        qt_app, hotkeys=hotkeys, pose=replace(START, rx=30.0)
    )
    window.movement.press_capture()
    hotkeys.hold_alt()
    hotkeys.press(NUMPAD4)
    assert window.movement.mode_text() == alt_hint()
    assert panel.pose().z == pytest.approx(START.z, abs=0.001)
    assert panel.pose().y == pytest.approx(START.y + 0.5, abs=0.001)


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

    def is_worker_alive(self) -> bool:
        return False


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


# --- защита от случайного ввода во время обмена ----------------------------


def test_keyboard_is_frozen_during_the_exchange(qt_app: QApplication) -> None:
    """Пока идёт обмен, клавиши не попадают ни в игру, ни в поле координат."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    window._set_busy(True)
    assert hotkeys.frozen is True
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    assert panel.pose() == START


def test_keyboard_is_released_after_the_exchange(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    assert hotkeys.frozen is False
    window.movement.press_capture()
    assert hotkeys.frozen is False


def test_write_field_does_not_start_a_step(qt_app: QApplication) -> None:
    """Случайная клавиша во время записи не запускает шаг и не переключает режим."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    window._set_busy(True)
    hotkeys.press(VK_MENU)
    hotkeys.release(VK_MENU)
    assert window.movement.mode_text() == "8/2 — вперёд/назад"
    window._set_busy(False)
    assert panel.pose() == START


def test_deadline_aborts_a_stuck_exchange(qt_app: QApplication) -> None:
    """Если панель не ответила, оверлей сам бросает задачу: окно не «висит»."""
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.press_capture()
    window._begin_busy("Читаю поля панели…")
    window._runner.submit = lambda *args, **kwargs: True  # type: ignore[method-assign]
    window._set_busy(True)
    window._runner.submit(lambda: None, on_success=lambda _r: None, on_error=lambda _m: None)
    assert window._runner.is_busy() is False
    window._runner.is_busy = lambda: True  # type: ignore[method-assign]
    window._action_deadline()
    assert hotkeys.frozen is False
    assert "прервано" in window.status_text().lower()


def test_abort_cancels_the_panel_and_forgets_the_pose(qt_app: QApplication) -> None:
    """«Прервать» останавливает обмен и требует новый «Считать»."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window._begin_busy("Шаг…")
    window._runner = _AbandoningRunner()  # type: ignore[assignment]
    window._abort_action()
    assert panel.cancel_calls >= 1
    assert window._pose is None
    assert "Считать" in window.status_text()


def test_failed_step_asks_to_read_again(qt_app: QApplication) -> None:
    """После отказа панели шаги не идут от старых координат."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    panel.reject.add(Field.X)
    window.movement.arrow(Direction.FORWARD).click()
    assert "Считать" in window.status_text()
    assert window._pose is None
    writes = list(panel.writes)
    window.movement.arrow(Direction.FORWARD).click()
    assert panel.writes == writes
    assert "Считать" in window.status_text()


def test_changed_panel_blocks_the_arrow(qt_app: QApplication) -> None:
    """Значение в панели поменяли — оверлей не затирает его, а просит пересчитать."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    panel.values[Field.X] = "1800.000"
    window.movement.arrow(Direction.FORWARD).click()
    assert panel.writes == []
    assert "Считать" in window.status_text()
    assert window._pose is None


class _StuckRunner:
    """Заглушка раннера, у которого поток не завершается никогда."""

    def abandon(self) -> bool:
        return True

    def is_worker_alive(self) -> bool:
        return True

    def is_busy(self) -> bool:
        return True

    def busy_seconds(self) -> float:
        return 30.0


def test_freeze_is_released_even_if_the_worker_never_stops(qt_app: QApplication) -> None:
    """Клавиатура не может остаться закрытой: ожидание выхода потока ограничено."""
    hotkeys = FakeHotkeySource()
    window, _panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window._runner = _StuckRunner()  # type: ignore[assignment]
    window._set_busy(True)
    assert hotkeys.frozen is True
    window._set_busy(False)
    assert hotkeys.frozen is True
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and hotkeys.frozen:
        qt_app.processEvents()
        time.sleep(0.02)
    assert hotkeys.frozen is False


# --- библиотека размеров ---------------------------------------------------


def _library(*items: ObjectSize, active: str | None = None) -> SizeLibrary:
    library = SizeLibrary()
    for item in items:
        library = library.with_item(item)
    return library.select(active)


def test_sizes_tab_adds_item_and_saves(qt_app: QApplication) -> None:
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("Ящик", 2.0, 1.0)
    window.sizes.press_add()
    assert [item.name for item in store.library.items] == ["Ящик"]
    assert store.saved
    assert window.sizes.row_names() == ["Ящик"]
    assert "Ящик" in window.status_text()


def test_sizes_tab_rejects_empty_name(qt_app: QApplication) -> None:
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("   ", 2.0, 1.0)
    window.sizes.press_add()
    assert store.library.items == ()
    assert "пустым" in window.status_text()


def test_sizes_tab_save_error_is_shown(qt_app: QApplication) -> None:
    store = FakeSizeStore()
    store.error = "диск переполнен"
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("Ящик", 2.0, 1.0)
    window.sizes.press_add()
    assert "диск переполнен" in window.status_text()
    assert window.sizes.row_names() == []


def test_sizes_tab_replaces_same_name(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("ящик", 3.0, 1.5)
    window.sizes.press_add()
    assert len(store.library.items) == 1
    assert store.library.items[0].length == pytest.approx(3.0)


def test_sizes_row_has_no_form_button(qt_app: QApplication) -> None:
    """Кнопки «В форму» больше нет: поля заполняет карандаш."""
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    texts = [item.text() for item in window.sizes.findChildren(QPushButton)]
    assert "В форму" not in texts
    assert "Удалить" not in texts


def test_sizes_row_uses_trash_icon(qt_app: QApplication) -> None:
    """Удаление — кнопка-значок корзины: без подписи, с иконкой и подсказкой."""
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    trash = window.sizes.trash("Ящик")
    assert trash is not None
    assert trash.text() == ""
    assert not trash.icon().isNull()
    assert trash.toolTip() == "Удалить предмет из библиотеки"
    assert trash.accessibleName() == "Удалить"


def test_sizes_trash_click_deletes_item(qt_app: QApplication) -> None:
    """Нажатие на корзину убирает предмет из библиотеки и со списка."""
    store = FakeSizeStore(
        _library(ObjectSize(name="Ящик", length=2.0, width=1.0), ObjectSize("Бочка", 1.0, 1.0))
    )
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_delete("Ящик")
    assert [item.name for item in store.library.items] == ["Бочка"]
    assert window.sizes.row_names() == ["Бочка"]
    assert window.sizes.trash("Ящик") is None


def test_sizes_tab_deletes_item(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_delete("Ящик")
    assert store.library.items == ()
    assert window.sizes.row_names() == []


def test_movement_lists_library_items(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0), active="Ящик"))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    assert window.movement.size_names() == ["— не выбран —", "Ящик"]


def test_size_button_sets_the_step(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0), active="Ящик"))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.movement.press_size_button(SizeUse.LENGTH).click()
    assert window.movement.current_step() == pytest.approx(2.0)
    window.movement.press_size_button(SizeUse.HALF_WIDTH).click()
    assert window.movement.current_step() == pytest.approx(0.5)


def test_size_half_length_sets_half_step(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Стол", length=1.6, width=0.8), active="Стол"))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.movement.press_size_button(SizeUse.HALF_LENGTH).click()
    assert window.movement.current_step() == pytest.approx(0.8)


def test_size_buttons_are_disabled_without_selection(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    assert not window.movement.press_size_button(SizeUse.LENGTH).isEnabled()
    assert window.movement.apply_size(SizeUse.LENGTH) is False
    assert "выберите предмет" in window.movement.warning_text().lower()
    assert window.movement.current_step() == pytest.approx(0.5)


def test_size_button_rejects_too_long_step(qt_app: QApplication) -> None:
    store = FakeSizeStore(
        _library(ObjectSize(name="Ангар", length=500.0, width=40.0), active="Ангар")
    )
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.movement.press_size_button(SizeUse.LENGTH).click()
    assert "Шаг должен быть" in window.movement.warning_text()
    assert window.movement.current_step() == pytest.approx(0.5)


def test_size_selection_is_saved(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.movement.select_size("Ящик")
    assert store.library.active == "Ящик"
    assert "Выбран «Ящик»" in window.status_text()


def test_deleting_active_item_clears_selection(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0), active="Ящик"))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_delete("Ящик")
    assert store.library.active is None
    assert window.movement.size_names() == ["— не выбран —"]


def test_broken_sizes_file_is_reported(qt_app: QApplication) -> None:
    store = FakeSizeStore()
    store.error = "файл размеров испорчен"
    window, panel, _settings, _cursor = make_window(qt_app, size_store=store)
    assert "Размеры не загружены" in window.status_text()
    # Работа продолжается: без библиотеки оверлей считает и двигает как обычно.
    window.movement.press_capture()
    assert panel.reads


def test_size_based_step_moves_the_object(qt_app: QApplication, tmp_path: Path) -> None:
    """Полный путь: добавили предмет, взяли его длину в шаг и сдвинули на неё."""
    path = tmp_path / "config" / "sizes.json"
    store = JsonSizeStore(path)
    window, panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("Ящик", 2.0, 1.0)
    window.sizes.press_add()
    window.movement.press_capture()
    window.movement.press_size_button(SizeUse.LENGTH).click()
    window.movement.arrow(Direction.FORWARD).click()
    assert panel.pose().x == pytest.approx(START.x + 2.0)
    saved = JsonSizeStore(path).load()
    assert [item.name for item in saved.items] == ["Ящик"]
    assert saved.active == "Ящик"


def test_sizes_form_has_no_steppers(qt_app: QApplication) -> None:
    """Длина и ширина вписываются руками: стрелок «+» и «−» в форме нет."""
    window, _panel, _settings, _cursor = make_window(qt_app)
    assert window.sizes.findChildren(QDoubleSpinBox) == []
    assert window.sizes.findChildren(QSpinBox) == []
    fields = [widget for widget in window.sizes.findChildren(QLineEdit)]
    assert len(fields) >= 3


def test_sizes_form_accepts_comma(qt_app: QApplication) -> None:
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("Ящик", "2,5", "1,2")
    window.sizes.press_add()
    assert store.library.items[0].length == pytest.approx(2.5)
    assert store.library.items[0].width == pytest.approx(1.2)


def test_sizes_form_rejects_empty_size(qt_app: QApplication) -> None:
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("Ящик", "", "1")
    window.sizes.press_add()
    assert store.library.items == ()
    assert "Длина должна быть числом" in window.status_text()


def test_search_filters_rows(qt_app: QApplication) -> None:
    store = FakeSizeStore(
        _library(
            ObjectSize(name="Ящик", length=2.0, width=1.0),
            ObjectSize(name="Паллета", length=1.2, width=0.8),
            ObjectSize(name="Стеллаж", length=3.0, width=1.5),
        )
    )
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    assert len(window.sizes.row_names()) == 3
    window.sizes.press_search("ящ")
    assert window.sizes.row_names() == ["Ящик"]
    assert "Найдено: 1 из 3" in window.sizes.list_hint()
    window.sizes.press_search("")
    assert len(window.sizes.row_names()) == 3


def test_search_reports_nothing_found(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_search("ангар")
    assert window.sizes.row_names() == []
    assert "Ничего не найдено" in window.sizes.list_hint()


def test_select_makes_item_active(qt_app: QApplication) -> None:
    store = FakeSizeStore(
        _library(
            ObjectSize(name="Ящик", length=2.0, width=1.0),
            ObjectSize(name="Паллета", length=1.2, width=0.8),
        )
    )
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_select("Паллета")
    assert store.library.active == "Паллета"
    assert "Паллета" in window.status_text()
    window.movement.press_size_button(SizeUse.LENGTH).click()
    assert window.movement.current_step() == pytest.approx(1.2)


# --- журнал действий -------------------------------------------------------


def test_user_actions_are_logged(qt_app: QApplication) -> None:
    """По журналу видно, что нажали и что из этого вышло."""
    window, _panel, _settings, _cursor = make_window(qt_app)
    JOURNAL.clear()
    window.movement.press_capture()
    log = JOURNAL.describe()
    assert "команда: считать координаты" in log
    assert "начал: считать координаты из панели" in log
    assert "задача «считать координаты» выполнена" in log
    assert "статус [ok]" in log


def test_hotkey_decision_is_logged(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _settings, _cursor = make_window(qt_app, hotkeys=hotkeys)
    JOURNAL.clear()
    hotkeys.press(NUMPAD0)
    hotkeys.release(NUMPAD0)
    log = JOURNAL.describe()
    assert "клавиша Num 0 нажата" in log
    assert "→ команда «Считать координаты»" in log
    assert "клавиша Num 0 отпущена" in log


def test_state_line_describes_what_is_happening(qt_app: QApplication) -> None:
    """Строка «жив» показывает занятость, шаг и координаты — как снимок состояния."""
    window, _panel, _settings, _cursor = make_window(qt_app)
    window.movement.press_capture()
    JOURNAL.clear()
    window._log_state()
    log = JOURNAL.describe()
    assert "жив: занято=нет" in log
    assert "шаг=0.5" in log
    assert "координаты=X 1850.000" in log


def test_busy_state_is_logged(qt_app: QApplication) -> None:
    window, _panel, _settings, _cursor = make_window(qt_app)
    JOURNAL.clear()
    window._begin_busy("Шаг вперёд…")
    window._set_busy(False)
    log = JOURNAL.describe()
    assert "начато действие: Шаг вперёд…" in log
    assert "занятость: включена" in log
    assert "занятость: снята" in log


def test_abort_and_deadline_are_logged(qt_app: QApplication) -> None:
    hotkeys = FakeHotkeySource()
    window, _panel, _settings, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window._begin_busy("Шаг…")
    window._runner = _AbandoningRunner()  # type: ignore[assignment]
    JOURNAL.clear()
    window._abort_action()
    assert "нажата кнопка «Прервать»" in JOURNAL.describe()

    window._runner = _StuckRunner()  # type: ignore[assignment]
    window._set_busy(True)
    JOURNAL.clear()
    window._action_deadline()
    assert "дедлайн" in JOURNAL.describe()


def test_failed_step_is_logged_with_reason(qt_app: QApplication) -> None:
    window, panel, _settings, _cursor = make_window(qt_app)
    window.movement.press_capture()
    panel.reject.add(Field.X)
    JOURNAL.clear()
    window.movement.arrow(Direction.FORWARD).click()
    log = JOURNAL.describe()
    assert "шаг" in log
    assert "провалилась" in log
    assert "Панель не приняла поле X" in log
    assert "статус [error]" in log


def test_search_finds_wall_by_word_and_number(qt_app: QApplication) -> None:
    """«Стена March, TID, …, 01-39» находится по слову и по номеру из диапазона."""
    wall = ObjectSize(name="Стена March, TID, Hood, Soup, New, 01-39", length=2.9, width=2.7)
    store = FakeSizeStore(_library(wall))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    for query in ("Стена", "Стена March", "Стена TID", "стена 05", "Стена 39"):
        window.sizes.press_search(query)
        assert window.sizes.row_names() == [wall.name], query
    window.sizes.press_search("Стена 40")
    assert window.sizes.row_names() == []


def test_search_finds_all_wall_variants(qt_app: QApplication) -> None:
    """Варианты — отдельные предметы, но ищутся общим словом «стена»."""
    names = [
        "Стена March, TID, Hood, Soup, New, 01-39",
        "Длинная стена 01-39, TID",
        "Стена с дверным проёмом 01-39, TID",
        "Полустена 01-39, TID",
        "четверть стены 01-39, TID",
        "Ящик",
    ]
    store = FakeSizeStore(_library(*(ObjectSize(name, 2.9, 2.7) for name in names)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_search("стена")
    assert len(window.sizes.row_names()) == 5
    assert "Найдено: 5 из 6" in window.sizes.list_hint()
    window.sizes.press_search("стена 05")
    assert len(window.sizes.row_names()) == 5
    window.sizes.press_search("полустена")
    assert window.sizes.row_names() == ["Полустена 01-39, TID"]


def test_search_distinguishes_number_padding(qt_app: QApplication) -> None:
    names = ["Стена 01-10", "Стена 001-10", "Стена 1-10"]
    store = FakeSizeStore(_library(*(ObjectSize(name, 2.9, 2.7) for name in names)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_search("Стена 01")
    assert window.sizes.row_names() == ["Стена 01-10"]
    window.sizes.press_search("Стена 001")
    assert window.sizes.row_names() == ["Стена 001-10"]
    window.sizes.press_search("Стена 1")
    assert window.sizes.row_names() == ["Стена 1-10"]


def test_pencil_puts_item_into_edit_mode(qt_app: QApplication) -> None:
    """Карандаш в строке берёт название и габариты в форму и включает правку."""
    store = FakeSizeStore(_library(ObjectSize("Ящик", 2.0, 1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    assert window.sizes.pencil("Ящик") is not None
    assert not window.sizes.pencil("Ящик").icon().isNull()
    window.sizes.press_pencil("Ящик")
    assert window.sizes.editing_name() == "Ящик"
    assert window.sizes.form_values() == ("Ящик", "2", "1")
    assert window.sizes.add_button_text() == "Сохранить изменения"
    assert "Правка «Ящик»" in window.sizes.form_hint()


def test_pencil_saves_new_name_and_sizes(qt_app: QApplication) -> None:
    """Правка меняет название и габариты, запись остаётся на своём месте."""
    store = FakeSizeStore(_library(ObjectSize("Ящик", 2.0, 1.0), ObjectSize("Бочка", 1.0, 1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_pencil("Ящик")
    window.sizes.fill_form("Ящик XL", 3.0, 1.5)
    window.sizes.press_add()
    assert [item.name for item in store.library.items] == ["Ящик XL", "Бочка"]
    assert store.library.find("Ящик XL") == ObjectSize("Ящик XL", 3.0, 1.5)
    assert store.saved
    assert window.sizes.row_names() == ["Ящик XL", "Бочка"]
    assert window.sizes.editing_name() is None
    assert window.sizes.add_button_text() == "Добавить в библиотеку"


def test_pencil_keeps_active_item_selected(qt_app: QApplication) -> None:
    """Переименование выбранного предмета не сбрасывает выбор."""
    store = FakeSizeStore(_library(ObjectSize("Ящик", 2.0, 1.0), active="Ящик"))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_pencil("Ящик")
    window.sizes.fill_form("Ящик XL", 2.5, 1.0)
    window.sizes.press_add()
    assert store.library.active == "Ящик XL"
    assert "Ящик XL" in window.sizes.row_names()[0]


def test_pencil_rejects_name_of_another_item(qt_app: QApplication) -> None:
    """Переименовать в занятое название нельзя: записи не сливаются молча."""
    store = FakeSizeStore(_library(ObjectSize("Ящик", 2.0, 1.0), ObjectSize("Бочка", 1.0, 1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_pencil("Ящик")
    window.sizes.fill_form("Бочка", 2.0, 1.0)
    window.sizes.press_add()
    assert [item.name for item in store.library.items] == ["Ящик", "Бочка"]
    assert "уже есть в библиотеке" in window.status_text()
    assert window.sizes.editing_name() == "Ящик"
    assert window.sizes.add_button_text() == "Сохранить изменения"


def test_clear_leaves_edit_mode(qt_app: QApplication) -> None:
    store = FakeSizeStore(_library(ObjectSize("Ящик", 2.0, 1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_pencil("Ящик")
    window.sizes.press_clear()
    assert window.sizes.editing_name() is None
    assert window.sizes.add_button_text() == "Добавить в библиотеку"
    assert window.sizes.form_values()[0] == ""


def test_plain_add_still_adds_new_item_after_edit(qt_app: QApplication) -> None:
    """После сохранения правки форма снова добавляет, а не переименовывает."""
    store = FakeSizeStore(_library(ObjectSize("Ящик", 2.0, 1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_pencil("Ящик")
    window.sizes.press_add()
    window.sizes.fill_form("Бочка", 1.0, 1.0)
    window.sizes.press_add()
    assert [item.name for item in store.library.items] == ["Ящик", "Бочка"]


def test_search_number_without_padding_falls_back(qt_app: QApplication) -> None:
    """«Стена 1» находит «01-39», когда точной записи нет, и говорит об этом."""
    store = FakeSizeStore(_library(ObjectSize("Стена 01-39", 2.9, 2.7)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_search("Стена 1")
    assert window.sizes.row_names() == ["Стена 01-39"]
    assert "без учёта нулей" in window.sizes.list_hint()


def test_search_exact_padding_still_wins(qt_app: QApplication) -> None:
    """Если точная запись есть, запасное сравнение не подмешивает лишние строки."""
    names = ["Стена 01-10", "Стена 1-10"]
    store = FakeSizeStore(_library(*(ObjectSize(name, 2.9, 2.7) for name in names)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_search("Стена 01")
    assert window.sizes.row_names() == ["Стена 01-10"]
    assert "без учёта нулей" not in window.sizes.list_hint()
    window.sizes.press_search("Стена 1")
    assert window.sizes.row_names() == ["Стена 1-10"]


def test_search_finds_wall_by_english_word_and_typo(qt_app: QApplication) -> None:
    """Лемма «стен» связана с «wall»: английское слово и смешанный алфавит находят стену."""
    store = FakeSizeStore(_library(ObjectSize("Стена March, TID, 01-39", 2.9, 2.7)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    for query in ("wall", "Cтена", "март"):
        window.sizes.press_search(query)
        assert window.sizes.row_names() == ["Стена March, TID, 01-39"], query


def test_sizes_search_narrows_while_typing(qt_app: QApplication) -> None:
    """Поиск на вкладке «Размеры» сужается по мере набора: «Mar» уже находит стену."""
    names = ["Стена March, TID, 01-39", "Stend March", "Ящик"]
    store = FakeSizeStore(_library(*(ObjectSize(name, 2.9, 2.7) for name in names)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    counts = []
    for query in ("M", "Ma", "Mar", "March", "March TID"):
        window.sizes.press_search(query)
        counts.append(len(window.sizes.row_names()))
    assert counts == sorted(counts, reverse=True)
    window.sizes.press_search("March TID")
    assert window.sizes.row_names() == ["Стена March, TID, 01-39"]


def test_navigation_has_item_search(qt_app: QApplication) -> None:
    """На вкладке «Навигация» есть тот же поиск по предметам."""
    names = ["Стена March, TID, 01-39", "Стена March 01-10", "Ящик"]
    store = FakeSizeStore(_library(*(ObjectSize(name, 2.9, 2.7) for name in names)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    assert window.movement.visible_size_names() == names
    window.movement.press_size_search("Mar")
    assert set(window.movement.visible_size_names()) == set(names[:2])
    assert "Найдено: 2 из 3" in window.movement.size_search_hint()
    window.movement.press_size_search("March 01")
    # «01» есть и в диапазоне 01-39, поэтому находятся обе стены
    assert set(window.movement.visible_size_names()) == set(names[:2])
    window.movement.press_size_search("March TID")
    assert window.movement.visible_size_names() == ["Стена March, TID, 01-39"]
    window.movement.press_size_search("нет такого")
    assert window.movement.visible_size_names() == []
    assert "Ничего не найдено" in window.movement.size_search_hint()


def test_navigation_search_selects_item(qt_app: QApplication) -> None:
    """Из отфильтрованного списка предмет выбирается как обычно."""
    names = ["Стена March", "Ящик"]
    store = FakeSizeStore(_library(*(ObjectSize(name, 2.9, 2.7) for name in names)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.movement.press_size_search("ящ")
    window.movement.select_size("Ящик")
    assert store.library.active == "Ящик"
    assert "Ящик" in window.status_text()


def test_navigation_search_keeps_active_item_visible(qt_app: QApplication) -> None:
    """Если фильтр скрыл выбранный предмет, он всё равно остаётся в списке."""
    store = FakeSizeStore(_library(ObjectSize("Ящик", 2.0, 1.0), ObjectSize("Стена", 2.9, 2.7)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.movement.select_size("Стена")
    window.movement.press_size_search("ящ")
    assert window.movement.visible_size_names() == ["Стена", "Ящик"]
    assert "Найдено: 1 из 2" in window.movement.size_search_hint()


def test_window_is_narrower_than_before() -> None:
    """Окно стало уже: 640 вместо 780 пикселей."""
    from map_overlay.ui.window import WINDOW_WIDTH

    assert WINDOW_WIDTH == 640


def test_mini_toggle_shrinks_and_restores(qt_app: QApplication) -> None:
    """Переключатель «Мини» сворачивает окно и возвращает прежний вид."""
    from map_overlay.ui.window import MINI_HEIGHT, MINI_WIDTH, WINDOW_HEIGHT, WINDOW_WIDTH

    window, _panel, _settings, _cursor = make_window(qt_app)
    window.show()
    window.set_mini(False)
    assert window.width() == WINDOW_WIDTH
    assert window.height() == WINDOW_HEIGHT
    assert window.mini_button_text() == "Мини"
    assert window.tab_bar_visible()

    window.press_mini()
    assert window.is_mini()
    assert window.width() == MINI_WIDTH
    assert window.height() == MINI_HEIGHT
    assert window.mini_button_text() == "Обычный"
    assert not window.tab_bar_visible()
    assert window.movement.is_compact()
    assert window.tabs_index() == 0

    window.press_mini()
    assert not window.is_mini()
    assert window.width() == WINDOW_WIDTH
    assert window.height() == WINDOW_HEIGHT
    assert window.mini_button_text() == "Мини"
    assert window.tab_bar_visible()
    assert not window.movement.is_compact()


def _long_library() -> SizeLibrary:
    """Библиотека с самым длинным названием: оно и раздувало окно."""
    return SizeLibrary().with_item(
        ObjectSize(name="Стена March, TID, Hood, Soup, New, 01-39", length=4.0, width=0.5)
    )


def test_every_tab_fits_window_width(qt_app: QApplication) -> None:
    """Содержимое вкладок не шире окна: горизонтальной прокрутки нет, лишнее обрезалось бы."""
    from map_overlay.ui.window import WINDOW_HEIGHT, WINDOW_WIDTH

    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(_long_library()))
    window.show()
    window.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
    qt_app.processEvents()
    for index, title in enumerate(window.tab_titles()):
        window.select_tab(index)
        qt_app.processEvents()
        assert window.tab_fits(index), f"вкладка «{title}» шире окна"


def test_mini_hides_item_picker_and_stays_narrow(qt_app: QApplication) -> None:
    """В мини-версии поиск и выбор предмета скрыты, а окно действительно узкое."""
    from map_overlay.ui.window import MINI_WIDTH

    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(_long_library()))
    window.show()
    assert window.movement.item_picker_visible()
    window.press_mini()
    qt_app.processEvents()
    assert not window.movement.item_picker_visible()
    assert window.width() == MINI_WIDTH
    assert window.tab_fits(0)
    window.press_mini()
    qt_app.processEvents()
    assert window.movement.item_picker_visible()


def test_pose_values_look_like_aligned_fields(qt_app: QApplication) -> None:
    """Координаты — поля-показания: моноширинный шрифт и выравнивание по правому краю."""
    from map_overlay.domain.formatting import format_value
    from map_overlay.ui.widgets import PoseGrid

    window, _panel, _store, _cursor = make_window(qt_app)
    grid = window.findChild(PoseGrid)
    assert grid is not None
    assert grid.text_of(Field.X) == "—"
    assert grid.alignment_of(Field.X) & Qt.AlignmentFlag.AlignRight
    window.movement.press_capture()
    assert grid.text_of(Field.X) == format_value(START.x, 3)
    assert grid.text_of(Field.RX) == format_value(START.rx, 3)


def test_pose_value_field_roles(qt_app: QApplication) -> None:
    """Значения позы помечены ролью поля, а не обычной подписи."""
    from PySide6.QtWidgets import QLabel

    window, _panel, _store, _cursor = make_window(qt_app)
    fields = [
        item for item in window.findChildren(QLabel) if item.property("role") == "poseDisplay"
    ]
    assert len(fields) == len(Field)
    assert all(item.property("empty") is True for item in fields)
    window.movement.press_capture()
    shown = [item for item in fields if item.text() != "—"]
    assert len(shown) == len(Field)
    assert all(item.property("empty") is False for item in shown)


def test_crosshair_center_has_no_step_text(qt_app: QApplication) -> None:
    """Шаг задаётся только полем «Шаг»: в центре крестовины подписи нет."""
    from map_overlay.ui.widgets import CenterMark
    from PySide6.QtWidgets import QLabel

    window, _panel, _store, _cursor = make_window(qt_app)
    pad = window.movement._pad
    assert isinstance(pad.center, CenterMark)
    texts = [item.text() for item in pad.findChildren(QLabel) if item.text()]
    assert not texts, texts
    assert not hasattr(pad, "set_step_text")


def test_hints_are_bullet_lists_with_hotkeys(qt_app: QApplication) -> None:
    """Подсказки — список с выделенными клавишами, а не простыня текста."""
    from PySide6.QtCore import Qt as QtCore

    window, _panel, _store, _cursor = make_window(qt_app)
    hints = window.movement._hint_labels
    assert len(hints) == 2
    for hint in hints:
        assert hint.textFormat() == QtCore.TextFormat.RichText
        assert "<li>" in hint.text()
        assert "<b>" in hint.text()


def test_search_and_item_fields_are_aligned(qt_app: QApplication) -> None:
    """«Поиск», «Предмет» и «Шаг» начинаются с одного места, счётчик — под поиском."""
    from PySide6.QtCore import QPoint

    window, _panel, _store, _cursor = make_window(qt_app)
    window.show()
    qt_app.processEvents()
    movement = window.movement
    left = [
        widget.mapTo(movement, QPoint(0, 0)).x()
        for widget in (movement._step_combo, movement._size_search, movement._size_combo)
    ]
    assert len(set(left)) == 1, left
    search = movement._size_search.mapTo(movement, QPoint(0, 0))
    hint = movement._size_hint.mapTo(movement, QPoint(0, 0))
    assert hint.y() > search.y() + movement._size_search.height() - 1


def test_disabled_button_shows_forbidden_cursor(qt_app: QApplication) -> None:
    """Выключенная кнопка не обещает клик: курсор «нельзя», а не «палец»."""
    from map_overlay.ui.widgets import button
    from PySide6.QtCore import Qt as QtCore

    item = button("Длина", widget_role="small")
    assert item.cursor().shape() == QtCore.CursorShape.PointingHandCursor
    item.setEnabled(False)
    assert item.cursor().shape() == QtCore.CursorShape.ForbiddenCursor
    item.setEnabled(True)
    assert item.cursor().shape() == QtCore.CursorShape.PointingHandCursor


def test_abort_button_is_a_danger_button(qt_app: QApplication) -> None:
    """«Прервать» — кнопка с красной обводкой, а не текст в углу."""
    from map_overlay.ui.theme import APP_QSS, DANGER_EDGE

    window, _panel, _store, _cursor = make_window(qt_app)
    assert window._abort_button.property("role") == "danger"
    assert window._abort_button.text() == "Прервать"
    assert DANGER_EDGE in APP_QSS


def test_mini_button_sits_next_to_title_and_badge_shows_calibration(
    qt_app: QApplication,
) -> None:
    """«Мини» — рядом с названием, калибровка — бейджем у правого края."""

    window, _panel, _store, _cursor = make_window(
        qt_app,
        settings=Settings(calibration=FULL_CALIBRATION, empty_point=Point(10, 10)),
    )
    window.show()
    qt_app.processEvents()
    assert window._mini_button.x() < window._calibration_label.x()
    assert window._calibration_label.property("role") == "badgeOk"

    empty, _panel, _store, _cursor = make_window(qt_app)
    empty.show()
    qt_app.processEvents()
    assert empty._calibration_label.property("role") == "badge"


def test_section_gap_is_wider_than_card_spacing() -> None:
    """Между карточками просторнее, чем внутри: блоки не слипаются."""
    from map_overlay.ui.widgets import CARD_SPACING, SECTION_GAP

    assert SECTION_GAP > CARD_SPACING


def test_scrollbar_is_thin_and_dark() -> None:
    """У прокрутки тонкий тёмный ползунок: она не выбивается из темы."""
    from map_overlay.ui.theme import APP_QSS

    assert "QScrollBar:vertical" in APP_QSS
    assert "QScrollBar::handle" in APP_QSS
    assert "width: 9px" in APP_QSS
    assert "QScrollArea { background: transparent; border: none; }" in APP_QSS


def test_window_title_does_not_wrap(qt_app: QApplication) -> None:
    """Заголовок окна — одной строкой: узкое окно иначе ломало шапку на два этажа."""
    from PySide6.QtWidgets import QLabel

    window, _panel, _store, _cursor = make_window(qt_app)
    titles = [
        item
        for item in window.findChildren(QLabel)
        if item.property("role") == "appTitle" and item.text() == "Mapper's Overlay Redux"
    ]
    assert titles
    assert all(not item.wordWrap() for item in titles)


def test_theme_styles_text_fields() -> None:
    """Поля ввода оформлены темой: иначе светлый текст был бы на белом фоне."""
    from map_overlay.ui.theme import APP_QSS

    assert "QLineEdit" in APP_QSS


def test_mini_remembers_previous_tab(qt_app: QApplication) -> None:
    """Из «Настроек» мини-версия уходит на навигацию, а обратно возвращает «Настройки»."""
    window, _panel, _settings, _cursor = make_window(qt_app)
    window.show()
    window.select_tab(3)
    window.press_mini()
    assert window.tabs_index() == 0
    window.press_mini()
    assert window.tabs_index() == 3


def test_window_has_application_icon(qt_app: QApplication) -> None:
    """У окна есть иконка приложения (её рисует map_overlay.ui.appicon)."""
    window, _panel, _settings, _cursor = make_window(qt_app)
    assert not window.windowIcon().isNull()
