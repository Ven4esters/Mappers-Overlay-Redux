"""Интерфейс: вкладки, сценарии чтения и шага, калибровка, настройки."""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.actions import Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.keynames import VK_NUMPAD8
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.domain.sizes import ObjectSize, SizeLibrary, SizeUse
from map_overlay.errors import ValidationError
from map_overlay.infrastructure.size_store import JsonSizeStore
from map_overlay.trace import JOURNAL
from map_overlay.ui.tabs.movement_tab import MovementTab
from map_overlay.ui.widgets import DecimalSpinBox
from map_overlay.ui.window import MainWindow
from PySide6.QtCore import QEvent, QLocale, Qt
from PySide6.QtGui import QValidator
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QPushButton,
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


@contextmanager
def _russian_locale() -> Iterator[None]:
    """Временно включить русскую локаль: на Windows с ней приходит десятичная запятая."""
    previous = QLocale()
    QLocale.setDefault(QLocale("ru_RU"))
    try:
        yield
    finally:
        QLocale.setDefault(previous)


def test_step_field_takes_dot_and_comma_in_russian_locale(qt_app: QApplication) -> None:
    """«Шаг» принимает «1.25» и «0,75» даже когда система просит запятую."""
    with _russian_locale():
        tab = MovementTab(default_step=0.5)
        tab.show()
        qt_app.processEvents()
        edit = tab._step_combo.lineEdit()
        for typed, expected in (("1.25", 1.25), ("0,75", 0.75), ("2", 2.0)):
            tab._step_combo.setCurrentText("0.5")
            edit.setFocus()
            qt_app.processEvents()
            QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClicks(edit, typed)
            edit.editingFinished.emit()
            qt_app.processEvents()
            assert tab.current_step() == pytest.approx(expected)
            # После правки поле показывает число с точкой, а не с запятой.
            assert "," not in tab.step_text()


def test_sizes_fields_take_dot_and_comma_in_russian_locale(qt_app: QApplication) -> None:
    """«Длина» и «Ширина» читают точку и запятую одинаково при русской локали."""
    with _russian_locale():
        window, _panel, _store, _cursor = make_window(qt_app)
        window.show()
        window._tabs.setCurrentIndex(1)
        qt_app.processEvents()
        tab = window.sizes
        for field, typed, expected in ((tab._length, "2.5", 2.5), (tab._width, "1,5", 1.5)):
            edit = field.lineEdit()
            edit.setFocus()
            QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClicks(edit, typed)
            field.interpretText()
            qt_app.processEvents()
            assert field.value() == pytest.approx(expected)


def test_delay_field_takes_dot_in_russian_locale(qt_app: QApplication) -> None:
    """Задержка набирается с точкой: «0.2» остаётся 0.2, а не превращается в 2."""
    with _russian_locale():
        window, _panel, _store, _cursor = make_window(qt_app)
        window.show()
        window._tabs.setCurrentIndex(3)
        qt_app.processEvents()
        spin = window.settings_tab._click
        edit = spin.lineEdit()
        edit.setFocus()
        QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(edit, "0.2")
        spin.interpretText()
        qt_app.processEvents()
        assert spin.value() == pytest.approx(0.2, abs=0.001)


def test_step_field_opens_for_typing_on_click(qt_app: QApplication) -> None:
    """Клик по «Шагу» ставит курсор в поле, и там есть место для цифр.

    Проверка ловит тот же класс поломки, что схлопнул поля «Длина»/«Ширина»:
    общая таблица стилей оставляла от поля ввода внутри списка одну полоску.
    """
    from PySide6.QtCore import QPoint

    tab = MovementTab(default_step=0.5)
    tab.show()
    qt_app.processEvents()
    combo = tab._step_combo
    edit = combo.lineEdit()
    assert combo.isEditable()
    assert edit.width() > 40
    assert edit.height() >= 14
    QTest.mouseClick(
        combo,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(16, combo.height() // 2),
    )
    qt_app.processEvents()
    assert edit.hasFocus()
    QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(edit, "3")
    assert tab.current_step() == pytest.approx(3.0)


def test_spin_box_accepts_comma_as_decimal_separator(qt_app: QApplication) -> None:
    """Запятая понимается как разделитель, буквы — нет.

    Тип результата ``validate`` зависит от версии PySide6 (6.8 — состояние, 6.12 —
    кортеж), поэтому состояние достаётся единым способом.
    """
    box = DecimalSpinBox()
    box.setDecimals(2)
    box.setRange(0.01, 100)

    def state(result: object) -> QValidator.State:
        return result[0] if isinstance(result, tuple) else cast(QValidator.State, result)

    assert state(box.validate("1,5", 1)) == QValidator.State.Acceptable
    assert state(box.validate("abc", 1)) == QValidator.State.Invalid


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
    assert window.movement.mode_text() == "Включено: высота"
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
    assert window.movement.mode_text() == "Включено: высота"
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
    assert window.movement.mode_text() == "Включено: высота"
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


def test_sizes_unit_lives_inside_the_field(qt_app: QApplication) -> None:
    """«м» — часть поля: единица в suffix, стрелок «+» и «−» нет, подписи «м» нет."""
    from PySide6.QtWidgets import QLabel

    window, _panel, _settings, _cursor = make_window(qt_app)
    spins = window.sizes.findChildren(QDoubleSpinBox)
    assert len(spins) == 2
    assert [spin.suffix() for spin in spins] == [" м", " м"]
    for spin in spins:
        assert spin.buttonSymbols() == QDoubleSpinBox.ButtonSymbols.NoButtons
    units = [item for item in window.sizes.findChildren(QLabel) if item.text() == "м"]
    assert units == []


def test_sizes_form_accepts_comma(qt_app: QApplication) -> None:
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("Ящик", "2,5", "1,2")
    window.sizes.press_add()
    assert store.library.items[0].length == pytest.approx(2.5)
    assert store.library.items[0].width == pytest.approx(1.2)


def test_sizes_field_never_goes_out_of_range(qt_app: QApplication) -> None:
    """Размер не бывает пустым или отрицательным: поле держит значение в пределах."""
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    length = window.sizes._length
    length.lineEdit().setText("")
    length.interpretText()
    assert length.minimum() <= length.value() <= length.maximum()
    length.setValue(0)
    assert length.value() == pytest.approx(length.minimum())
    window.sizes.fill_form("Ящик", "0.001", "1")
    window.sizes.press_add()
    assert len(store.library.items) == 1
    assert store.library.items[0].length == pytest.approx(length.minimum())


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
    assert window.sizes.form_values() == ("Ящик", "2 м", "1 м")
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
    """Переключатель «Мини» сворачивает окно и возвращает прежний вид.

    Ширина и высота сравниваются с константой «не меньше», а не на равенство: на Windows
    и при увеличенном системном шрифте окно крупнее эталона, иначе вкладка обрезалась бы.
    Мини-версии не хватало 43 пикселей на третий переключатель — теперь она дорастает.
    """
    from map_overlay.ui.window import MINI_HEIGHT, MINI_WIDTH, WINDOW_HEIGHT, WINDOW_WIDTH

    window, _panel, _settings, _cursor = make_window(qt_app)
    window.show()
    window.set_mini(False)
    full_width = window.width()
    full_height = window.height()
    assert full_width >= WINDOW_WIDTH
    assert full_height >= WINDOW_HEIGHT
    assert window.mini_button_text() == "Мини"
    assert window.tab_bar_visible()

    window.press_mini()
    assert window.is_mini()
    assert window.width() < full_width
    assert window.width() >= MINI_WIDTH
    assert window.height() >= MINI_HEIGHT
    assert window.mini_button_text() == "Обычный"
    assert not window.tab_bar_visible()
    assert window.movement.is_compact()
    assert window.tabs_index() == 0

    window.press_mini()
    assert not window.is_mini()
    assert window.width() == full_width
    assert window.height() == full_height
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


def test_big_system_font_keeps_tabs_and_fields_aligned(qt_app: QApplication) -> None:
    """Крупный системный шрифт (как Segoe UI на Windows) не обрезает вкладки.

    На Windows подписи и поля шире эталонных: вкладка «Навигация» вылезала за окно,
    а поле шага съезжало влево от «Поиска» и «Предмета». Проверка воспроизводит это
    шрифтом в 12 пунктов — так дефект виден и на эталонном Linux.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont

    base_font = qt_app.font()
    qt_app.setFont(QFont(base_font.family(), 12))
    window: MainWindow | None = None
    try:
        window, _panel, _store, _cursor = make_window(
            qt_app, size_store=FakeSizeStore(_long_library())
        )
        window.show()
        qt_app.processEvents()
        for index, title in enumerate(window.tab_titles()):
            window.select_tab(index)
            qt_app.processEvents()
            assert window.tab_fits(index), f"вкладка «{title}» шире окна при крупном шрифте"
        movement = window.movement
        left = [
            widget.mapTo(movement, QPoint(0, 0)).x()
            for widget in (movement._step_combo, movement._size_search, movement._size_combo)
        ]
        assert len(set(left)) == 1, left
        window.press_mini()
        qt_app.processEvents()
        assert window.tab_fits(0)
    finally:
        # Окно создано под другой шрифт: убрать его до возврата шрифта, иначе Qt
        # разбирает виджеты с чужими метриками уже после теста и падает на выходе.
        if window is not None:
            window.close()
            window.deleteLater()
            qt_app.processEvents()
        qt_app.setFont(base_font)


def test_mini_hides_item_picker_and_stays_narrow(qt_app: QApplication) -> None:
    """В мини-версии поиск и выбор предмета скрыты, а окно действительно узкое."""
    from map_overlay.ui.window import MINI_WIDTH

    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(_long_library()))
    window.show()
    assert window.movement.item_picker_visible()
    window.press_mini()
    qt_app.processEvents()
    assert not window.movement.item_picker_visible()
    assert window.width() >= MINI_WIDTH
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
    from map_overlay.ui.widgets import PoseGrid
    from PySide6.QtWidgets import QLabel

    window, _panel, _store, _cursor = make_window(qt_app)
    grid = window.findChild(PoseGrid)
    assert grid is not None
    fields = [item for item in grid.findChildren(QLabel) if item.property("role") == "poseDisplay"]
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


def test_movement_help_hides_behind_the_card_icon(qt_app: QApplication) -> None:
    """Справка «Сдвига» не занимает пол-вкладки: её показывает ⓘ у заголовка."""
    from PySide6.QtWidgets import QLabel

    window, _panel, _store, _cursor = make_window(qt_app)
    card = window.movement._move_card
    help_text = card.hint()
    for key in ("Num 8", "Num 4/6", "Alt", "RY"):
        assert key in help_text
    assert card._info.toolTip() == help_text
    assert not [item for item in card.findChildren(QLabel) if "<li>" in item.text()]


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


def test_abort_button_is_armed_only_while_busy(qt_app: QApplication) -> None:
    """«Прервать» — кнопка, а не текст в углу: в покое серая, во время обмена красная."""
    from map_overlay.ui.theme import APP_QSS, ERROR

    window, _panel, _store, _cursor = make_window(qt_app)
    abort = window._abort_button
    assert abort.property("role") == "abort"
    assert abort.text() == "Прервать"
    armed = APP_QSS.split('QPushButton[role="abort"]:enabled {', 1)[1].split("}", 1)[0]
    assert ERROR in armed
    assert "color: #ffffff" in armed


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


def test_value_field_shows_dash_for_missing_value(qt_app: QApplication) -> None:
    """Пустое показание — приглушённый прочерк, а не пустая рамка."""
    from map_overlay.ui.widgets import ValueField

    field = ValueField()
    assert field.text() == "—"
    assert field.property("empty") is True
    field.set_value("-12.500")
    assert field.text() == "-12.500"
    assert field.property("empty") is False
    assert field.value() == "-12.500"
    field.set_value(None)
    assert field.text() == "—"
    assert field.value() is None


def test_calibration_points_are_display_fields(qt_app: QApplication) -> None:
    """Точки панели — такие же поля-показания, как координаты на «Навигации»."""
    from map_overlay.ui.tabs.calibration_tab import CalibrationTab
    from map_overlay.ui.widgets import ValueField

    cursor = FakeCursor(Point(700, 500))
    tab = CalibrationTab(cursor=cursor, points={}, countdown_seconds=0, tick_ms=0)
    values = list(tab._value_labels.values())
    assert len(values) == len(Field) + 1
    assert all(isinstance(item, ValueField) for item in values)
    assert all(item.text() == "—" for item in values)
    assert all(item.property("empty") is True for item in values)
    assert all(item.alignment() & Qt.AlignmentFlag.AlignRight for item in values)

    tab.capture_now(Field.X)
    filled = tab._value_labels[Field.X.value]
    assert filled.text() == "700, 500"
    assert filled.property("empty") is False


def test_calibration_show_is_disabled_without_point(qt_app: QApplication) -> None:
    """«Показать» без сохранённой точки недоступна — кнопка не обещает переход."""
    from map_overlay.ui.tabs.calibration_tab import CalibrationTab

    cursor = FakeCursor(Point(640, 480))
    tab = CalibrationTab(cursor=cursor, points={}, countdown_seconds=0, tick_ms=0)
    show = tab._show_buttons[Field.Y.value]
    assert not show.isEnabled()
    assert "Сначала задайте" in show.toolTip()
    assert tab._show_buttons[Field.X.value].isEnabled() is False

    tab.capture_now(Field.Y)
    assert show.isEnabled()
    assert show.toolTip() == "Перевести курсор в сохранённую точку"


def test_calibration_help_hides_behind_the_card_icon(qt_app: QApplication) -> None:
    """Справка калибровки — в ⓘ карточки: на вкладке нет простыни текста."""
    from map_overlay.ui.tabs.calibration_tab import CalibrationTab
    from PySide6.QtWidgets import QLabel

    tab = CalibrationTab(cursor=FakeCursor(), points={})
    help_text = tab._card.hint()
    for key in ("Задать", "Показать", "Сохранить F", "зелёным"):
        assert key in help_text
    assert tab._card._info.toolTip() == help_text
    assert not [item for item in tab.findChildren(QLabel) if "<li>" in item.text()]
    assert not [item for item in tab.findChildren(QLabel) if item.property("role") == "hint"]


def test_sizes_form_puts_sizes_in_one_row(qt_app: QApplication) -> None:
    """«Длина» и «Ширина» стоят рядом и заполняют карточку, а не жмутся влево."""
    from PySide6.QtCore import QPoint

    window, _panel, _store, _cursor = make_window(qt_app)
    window.show()
    window._tabs.setCurrentIndex(1)
    qt_app.processEvents()
    tab = window.sizes
    length = tab._length.mapTo(tab, QPoint(0, 0))
    width = tab._width.mapTo(tab, QPoint(0, 0))
    name = tab._name.mapTo(tab, QPoint(0, 0))
    assert length.y() == width.y()
    assert length.x() < width.x()
    assert length.x() == name.x()
    assert tab._length.width() == tab._width.width()
    # Поля шире прежней «узкой» колонки и вместе занимают почти всю карточку.
    assert tab._length.width() > 150
    right = width.x() + tab._width.width()
    assert right >= tab._form_card.width() - 40
    assert tab._length.text().endswith(" м")
    assert tab._width.text().endswith(" м")


def test_sizes_rows_put_sizes_under_the_name(qt_app: QApplication) -> None:
    """Габариты стоят сразу под названием и начинаются с того же места."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QLabel

    library = _library(
        ObjectSize(name="Стена March", length=4.0, width=0.5),
        ObjectSize(name="Дверь", length=1.0, width=0.2),
    )
    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(library))
    window.sizes.show()
    qt_app.processEvents()
    tab = window.sizes
    names = tab.row_names()
    assert len(names) == 2

    rows = [tab._list.itemWidget(tab._list.item(index)) for index in range(tab._list.count())]
    sizes = [
        item
        for row in rows
        for item in row.findChildren(QLabel)
        if item.property("role") == "rowSize" and "×" in item.text()
    ]
    assert len(sizes) == len(names)
    assert [item.text() for item in sizes] == ["4 × 0.5 м", "1 × 0.2 м"]
    for row in rows:
        name = next(item for item in row.findChildren(QLabel) if item.property("role") == "rowName")
        size = next(item for item in row.findChildren(QLabel) if item.property("role") == "rowSize")
        assert size.mapTo(row, QPoint(0, 0)).y() > name.mapTo(row, QPoint(0, 0)).y()
        assert size.mapTo(row, QPoint(0, 0)).x() == name.mapTo(row, QPoint(0, 0)).x()


def test_long_name_row_grows_instead_of_overlapping(qt_app: QApplication) -> None:
    """Длинное название переносится: строка не ниже своего текста и не наезжает на соседнюю."""
    from PySide6.QtWidgets import QLabel

    library = _library(
        ObjectSize(
            name="Стена March, TID, Hood, Soup, New, 01-39, бетон, проём",
            length=4.0,
            width=0.5,
        ),
        ObjectSize(name="Дверь", length=1.0, width=0.2),
    )
    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(library))
    window.show()
    window._tabs.setCurrentIndex(1)
    # Строки получают ширину не сразу: высота пересчитывается по resizeEvent.
    for _ in range(4):
        qt_app.processEvents()
    tab = window.sizes
    rows = [tab._list.itemWidget(tab._list.item(index)) for index in range(tab._list.count())]
    assert len(rows) == 2
    needed = []
    for row in rows:
        caption = next(
            item for item in row.findChildren(QLabel) if item.property("role") == "rowName"
        )
        needed.append(caption.heightForWidth(caption.width()))
        assert row.height() >= caption.heightForWidth(caption.width()), caption.text()
    assert needed[0] > needed[1], needed


def test_sizes_counter_sits_under_search_field(qt_app: QApplication) -> None:
    """«Предметов: 5» — мелким под полем поиска, а не в одной строке с ним."""
    from PySide6.QtCore import QPoint

    window, _panel, _store, _cursor = make_window(qt_app)
    window.show()
    window._tabs.setCurrentIndex(1)
    qt_app.processEvents()
    tab = window.sizes
    search = tab._search.mapTo(tab, QPoint(0, 0))
    counter = tab._empty_label.mapTo(tab, QPoint(0, 0))
    assert tab._empty_label.property("role") == "hint"
    assert counter.y() > search.y() + tab._search.height() - 1
    assert counter.x() == search.x()


def test_sizes_help_hides_behind_info_icon(qt_app: QApplication) -> None:
    """Справка не висит стеной текста: её показывает ⓘ у заголовка карточки."""
    from PySide6.QtWidgets import QLabel

    window, _panel, _store, _cursor = make_window(qt_app)
    tab = window.sizes
    texts = [item.text() for item in tab.findChildren(QLabel)]
    assert not [text for text in texts if "<li>" in text]
    info = tab._form_card._info
    assert info.text() == ""
    assert not info.pixmap().isNull()
    assert info.property("role") == "info"
    assert info.isVisible() or not tab.isVisible()
    assert info.cursor().shape() == Qt.CursorShape.WhatsThisCursor
    assert info.toolTip() == tab.form_hint()
    assert "Название — ключ" in tab.form_hint()
    form_help, list_help = tab.help_texts()
    assert form_help == tab.form_hint()
    assert "Поиск" in list_help
    assert "Ctrl+Z" in list_help


def test_sizes_trash_is_danger_and_pencil_is_not(qt_app: QApplication) -> None:
    """Удаление помечено красным, правка — нет."""
    library = _library(ObjectSize(name="Ящик", length=2.0, width=1.0))
    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(library))
    tab = window.sizes
    trash = tab.trash("Ящик")
    pencil = tab.pencil("Ящик")
    assert trash is not None and pencil is not None
    assert trash.property("severity") == "danger"
    assert trash.property("role") == "icon"
    assert pencil.property("severity") is None
    assert trash.width() == pencil.width()


def test_settings_delay_fields_align_by_columns(qt_app: QApplication) -> None:
    """Поля задержек стоят двумя столбцами, а подписи — своей колонкой."""
    from PySide6.QtCore import QPoint

    window, _panel, _store, _cursor = make_window(qt_app)
    tab = window.settings_tab
    window.show()
    window._tabs.setCurrentIndex(3)
    qt_app.processEvents()
    fields = [tab._click, tab._select, tab._copy, tab._paste]
    left = {item.mapTo(tab, QPoint(0, 0)).x() for item in fields[:2]}
    right = {item.mapTo(tab, QPoint(0, 0)).x() for item in fields[2:]}
    assert len(left) == 1
    assert len(right) == 1
    assert left.pop() < right.pop()


def test_settings_hotkey_clear_is_small_danger(qt_app: QApplication) -> None:
    """«✕» снимает привязку: компактная кнопка с красной рамкой, не выше «Изменить»."""
    window, _panel, _store, _cursor = make_window(qt_app)
    tab = window.settings_tab
    window.show()
    window._tabs.setCurrentIndex(3)
    qt_app.processEvents()
    clears = [
        child
        for child in tab.findChildren(QPushButton)
        if child.text() == "✕" and child.property("severity") == "danger"
    ]
    assert len(clears) == len(Action)
    assert all(item.property("role") == "small" for item in clears)
    change = next(child for child in tab.findChildren(QPushButton) if child.text() == "Изменить")
    assert clears[0].height() <= change.height()


def test_settings_help_hides_behind_card_icons(qt_app: QApplication) -> None:
    """Справка «Настроек» — в ⓘ каждой карточки, а не списком под полями."""
    from PySide6.QtWidgets import QLabel

    window, _panel, _store, _cursor = make_window(qt_app)
    tab = window.settings_tab
    assert "20–40 мс" in tab._delay_card.hint()
    assert "Шаг по умолчанию" in tab._value_card.hint()
    assert "NumLock" in tab._hotkey_card.hint()
    for card in (tab._delay_card, tab._value_card, tab._hotkey_card):
        assert card._info.isVisible() or not tab.isVisible()
        assert card._info.toolTip() == card.hint()
    assert not [item for item in tab.findChildren(QLabel) if "<li>" in item.text()]
    # Настройки не отменяются: об этом в справке нечего обещать.
    assert "Ctrl+Z" not in tab._hotkey_card.hint()


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


def test_theme_makes_status_instruction_readable() -> None:
    """Строка состояния — 12 px и светлее: инструкцию внизу видно, а не угадывается."""
    from map_overlay.ui.theme import APP_QSS

    assert "QLabel#status { font-size: 12px; }" in APP_QSS
    status = APP_QSS.split('QLabel#status[role="muted"] {', 1)[1].split("}", 1)[0]
    assert "#a0a0a0" in status


def test_theme_gives_inputs_room_inside_the_frame() -> None:
    """Текст не липнет к рамке: у полей ввода внутренние отступы 8 × 12."""
    from map_overlay.ui.theme import APP_QSS

    fields = APP_QSS.split("QLineEdit {", 1)[1].split("}", 1)[0]
    assert "padding: 8px 12px" in fields
    spins = APP_QSS.split("QComboBox, QSpinBox, QDoubleSpinBox {", 1)[1].split("}", 1)[0]
    assert "padding: 8px 12px" in spins


def test_sizes_selected_row_is_highlighted_across_full_width(
    qt_app: QApplication,
) -> None:
    """Текущий предмет подсвечен фоном на всю ширину строки, а не галочкой."""
    from map_overlay.ui.theme import APP_QSS
    from PySide6.QtWidgets import QAbstractItemView

    library = _library(
        ObjectSize(name="Ящик", length=2.0, width=1.0),
        ObjectSize(name="Дверь", length=1.0, width=0.2),
    ).select("Ящик")
    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(library))
    window.show()
    window._tabs.setCurrentIndex(1)
    for _ in range(3):
        qt_app.processEvents()
    tab = window.sizes
    current = tab._list.currentItem()
    assert current is not None
    assert current.data(Qt.ItemDataRole.UserRole) == "Ящик"
    row = tab._list.itemWidget(current)
    # Строка занимает всю ширину списка: остаётся только зазор между строками.
    rect = tab._list.visualItemRect(current)
    assert rect.width() >= tab._list.viewport().width() - 6
    assert row.width() == rect.width()
    assert tab._list.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert "QListWidget#sizesList::item:selected" in APP_QSS
    assert "background: rgba(59, 130, 246, 0.18)" in APP_QSS


def test_sizes_row_reads_name_first_and_sizes_second(qt_app: QApplication) -> None:
    """В строке главное — название; габариты — справа и тише; действия не кричат."""
    from PySide6.QtWidgets import QLabel

    library = _library(ObjectSize(name="Ящик", length=2.0, width=1.0))
    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(library))
    window.show()
    window._tabs.setCurrentIndex(1)
    qt_app.processEvents()
    tab = window.sizes
    row = tab._list.itemWidget(tab._list.item(0))
    labels = row.findChildren(QLabel)
    name = next(item for item in labels if item.property("role") == "rowName")
    size = next(item for item in labels if item.property("role") == "rowSize")
    assert name.text() == "Ящик"
    assert size.text() == "2 × 1 м"
    # Размеры — под названием, а не в середине строки между текстом и кнопками.
    assert size.y() > name.y()
    assert size.x() == name.x()
    assert size.x() + size.width() < row.width()

    ghost = next(item for item in row.findChildren(QPushButton) if item.text() == "Выбрать")
    assert ghost.property("role") == "ghost"
    for icon_button in (tab.pencil("Ящик"), tab.trash("Ящик")):
        assert icon_button is not None
        assert icon_button.property("role") == "icon"
        # Иконка — квадрат на прозрачном фоне: подсветка появляется только при наведении.
        assert icon_button.width() == icon_button.height()
        assert icon_button.icon().isNull() is False


def test_sizes_clear_button_is_a_destructive_outline(qt_app: QApplication) -> None:
    """«Очистить» — красная контурная кнопка: краснеет при наведении."""
    from map_overlay.ui.theme import APP_QSS

    window, _panel, _store, _cursor = make_window(qt_app)
    clear = window.sizes._clear_button
    assert clear.property("role") == "clear"
    block = APP_QSS.split('QPushButton[role="clear"]:hover {', 1)[1].split("}", 1)[0]
    assert "#ef4444" in block


def test_mini_and_calibration_badge_are_one_pill(qt_app: QApplication) -> None:
    """«Мини» и бейдж калибровки — пилюли одного вида и одной высоты."""
    from map_overlay.ui.theme import APP_QSS

    window, _panel, _store, _cursor = make_window(
        qt_app,
        settings=Settings(calibration=FULL_CALIBRATION, empty_point=Point(10, 10)),
    )
    window.show()
    qt_app.processEvents()
    mini = window._mini_button
    badge = window._calibration_label
    assert mini.property("role") == "badge"
    assert abs(mini.height() - badge.height()) <= 1
    assert 'QPushButton[role="badge"]' in APP_QSS


def test_abort_button_is_readable_while_idle(qt_app: QApplication) -> None:
    """В покое «Прервать» — серая кнопка с читаемым текстом, а не тёмное пятно."""
    from map_overlay.ui.theme import APP_QSS, BORDER

    window, _panel, _store, _cursor = make_window(qt_app)
    abort = window._abort_button
    assert not abort.isHidden()
    assert not abort.isEnabled()
    idle = APP_QSS.split('QPushButton[role="abort"] {', 1)[1].split("}", 1)[0]
    assert BORDER in idle
    assert "color: #c2cbdb" in idle


def test_sizes_placeholder_is_short_and_example_lives_in_help(
    qt_app: QApplication,
) -> None:
    """Плейсхолдер не обрезается: «Введите название…», а пример — в справке ⓘ."""
    window, _panel, _store, _cursor = make_window(qt_app)
    tab = window.sizes
    assert tab._name.placeholderText() == "Введите название…"
    assert "Ящик" not in tab._name.placeholderText()
    assert "Ящик" in tab.form_hint()


def test_sizes_choose_button_is_visible_in_both_states(qt_app: QApplication) -> None:
    """«Выбрать» читается: у выбранного предмета — белый текст на подложке."""
    from map_overlay.ui.theme import APP_QSS

    library = _library(
        ObjectSize(name="Ящик", length=2.0, width=1.0),
        ObjectSize(name="Дверь", length=1.0, width=0.2),
    ).select("Ящик")
    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(library))
    window.sizes.show()
    qt_app.processEvents()
    tab = window.sizes
    rows = {
        tab._list.item(index).data(Qt.ItemDataRole.UserRole): tab._list.itemWidget(
            tab._list.item(index)
        )
        for index in range(tab._list.count())
    }
    choose = {
        name: next(item for item in row.findChildren(QPushButton) if item.text() == "Выбрать")
        for name, row in rows.items()
    }
    assert not choose["Ящик"].isEnabled()
    assert choose["Дверь"].isEnabled()
    base = APP_QSS.split('QPushButton[role="ghost"] {', 1)[1].split("}", 1)[0]
    assert "color: #b9c4d6" in base
    picked = APP_QSS.split('QPushButton[role="ghost"]:disabled {', 1)[1].split("}", 1)[0]
    assert "color: #e6ebf3" in picked
    assert "rgba(148, 163, 184, 0.16)" in picked


def test_sizes_icons_are_equal_and_trash_turns_white_on_hover(
    qt_app: QApplication,
) -> None:
    """Карандаш и корзина одного размера; под курсом корзина белеет на красном фоне."""
    from map_overlay.ui.tabs.sizes_tab import _trash_icon
    from map_overlay.ui.theme import APP_QSS, DANGER_TEXT
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon

    library = _library(ObjectSize(name="Ящик", length=2.0, width=1.0))
    window, _panel, _store, _cursor = make_window(qt_app, size_store=FakeSizeStore(library))
    tab = window.sizes
    pencil = tab.pencil("Ящик")
    trash = tab.trash("Ящик")
    assert pencil is not None and trash is not None
    assert pencil.size() == trash.size()
    assert pencil.iconSize() == trash.iconSize()

    icon = _trash_icon(QColor(DANGER_TEXT), hover=QColor("#ffffff"))
    normal = icon.pixmap(QSize(24, 24), QIcon.Mode.Normal).toImage()
    active = icon.pixmap(QSize(24, 24), QIcon.Mode.Active).toImage()
    assert normal != active
    colours = {
        active.pixelColor(x, 12).name()
        for x in range(active.width())
        if active.pixelColor(x, 12).alpha() > 200
    }
    assert "#ffffff" in colours
    hover_rule = APP_QSS.split('QPushButton[severity="danger"][role="icon"]:hover {', 1)[1]
    assert "rgba(239, 68, 68" in hover_rule.split("}", 1)[0]


def test_mini_button_reacts_to_hover() -> None:
    """«Мини» — кнопка: при наведении меняется фон, иначе она выглядит бейджем."""
    from map_overlay.ui.theme import APP_QSS

    hover = APP_QSS.split('QPushButton[role="badge"]:hover {', 1)[1].split("}", 1)[0]
    assert "background:" in hover
    assert "color: #ffffff" in hover


# --- режим «всегда считать позицию» ---------------------------------------


def test_always_read_is_off_by_default(qt_app: QApplication) -> None:
    """Режим выключен по умолчанию: шаг по-прежнему требует «Считать»."""
    window, panel, _store, _cursor = make_window(qt_app)
    assert not window.movement.always_read_enabled()
    assert not window.movement.arrow(Direction.FORWARD).isEnabled()
    window.movement.arrow(Direction.FORWARD).click()
    assert "Считать" in window.status_text()
    assert panel.writes == []


def test_always_read_moves_without_capture(qt_app: QApplication) -> None:
    """С режимом шаг выполняется сразу: координаты оверлей читает сам."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.always_read_box().setChecked(True)
    assert window.movement.arrow(Direction.FORWARD).isEnabled()
    window.movement.arrow(Direction.FORWARD).click()
    assert panel.reads[:6] == list(Field)
    assert panel.pose().x == pytest.approx(START.x + 0.5, abs=0.001)
    assert "позиция считана заново" in window.status_text()


def test_always_read_follows_the_position_changed_in_game(qt_app: QApplication) -> None:
    """Позицию двигали в игре — режим не ругается, а шагает от свежих чисел."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.always_read_box().setChecked(True)
    panel.values[Field.X] = "10.500"
    window.movement.arrow(Direction.FORWARD).click()
    assert panel.pose().x == pytest.approx(11.0, abs=0.001)
    assert "Нажмите «Считать»" not in window.status_text()


def test_always_read_toggle_is_saved_to_settings(qt_app: QApplication) -> None:
    """Выбор режима сохраняется в settings.json и переживает перезапуск."""
    window, _panel, store, _cursor = make_window(qt_app)
    window.movement.always_read_box().setChecked(True)
    assert store.saved[-1].always_read_pose is True
    assert "Режим «Всегда считать позицию» включён" in window.status_text()
    window.movement.always_read_box().setChecked(False)
    assert store.saved[-1].always_read_pose is False


def test_always_read_restores_from_settings(qt_app: QApplication) -> None:
    """Сохранённый режим включается при запуске и виден на вкладке."""
    settings = replace(Settings(), always_read_pose=True)
    window, _panel, _store, _cursor = make_window(qt_app, settings=settings)
    assert window.movement.always_read_enabled()
    assert window.movement.arrow(Direction.FORWARD).isEnabled()


def test_always_read_toggle_keeps_pose_and_history(qt_app: QApplication) -> None:
    """Переключение режима — настройка, а не новые координаты: поза и история целы."""
    window, _panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.arrow(Direction.FORWARD).click()
    window.movement.always_read_box().setChecked(True)
    assert window.history().can_undo
    assert window.movement.step_text()
    assert window.undo()


def test_always_read_hold_reads_once_per_press(qt_app: QApplication) -> None:
    """Удержание читает поля один раз: дальше шаги идут от только что записанной позы."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.always_read_box().setChecked(True)
    hotkeys.press(VK_NUMPAD8)
    assert len(panel.reads) >= 6
    for _ in range(3):
        window._hold_tick()
    # Поля целиком читаются только на нажатии: повторные шаги уходят от записанной позы.
    assert panel.reads.count(Field.RZ) == 1
    assert panel.pose().x == pytest.approx(START.x + 2.0, abs=0.001)


def test_always_read_works_with_the_tilt_mode(qt_app: QApplication) -> None:
    """Режим высоты работает вместе с чтением: Num 8 поднимает предмет."""
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys)
    window.movement.always_read_box().setChecked(True)
    window._set_tilt(True)
    hotkeys.press(VK_NUMPAD8)
    assert panel.pose().z == pytest.approx(START.z + 0.5, abs=0.001)
    assert panel.pose().x == pytest.approx(START.x, abs=0.001)


# --- «Прямой шаг 4/6/8/2» --------------------------------------------------


def test_straight_cardinal_is_off_by_default(qt_app: QApplication) -> None:
    """Переключатель выключен по умолчанию: формулы поворота работают как раньше."""
    window, _panel, _store, _cursor = make_window(qt_app)
    assert not window.movement.straight_enabled()
    assert window.movement.straight_box().text() == "Прямой шаг 4/6/8/2"


def test_straight_cardinal_toggle_is_saved_to_settings(qt_app: QApplication) -> None:
    """Выбор переключателя сохраняется в settings.json и переживает перезапуск."""
    window, _panel, store, _cursor = make_window(qt_app)
    window.movement.straight_box().setChecked(True)
    assert store.saved[-1].straight_cardinal is True
    assert "«Прямой шаг 4/6/8/2» включён" in window.status_text()
    window.movement.straight_box().setChecked(False)
    assert store.saved[-1].straight_cardinal is False
    assert "выключен" in window.status_text()


def test_straight_cardinal_restores_from_settings(qt_app: QApplication) -> None:
    """Сохранённый режим включается при запуске и виден на вкладке."""
    settings = replace(Settings(), straight_cardinal=True)
    window, _panel, _store, _cursor = make_window(qt_app, settings=settings)
    assert window.movement.straight_enabled()


def test_straight_cardinal_height_ignores_the_tilt(qt_app: QApplication) -> None:
    """С режимом Alt+Num 8 поднимает предмет строго по Z: наклон RY шаг вбок не уводит."""
    pose = Pose(x=1850.0, y=1850.0, z=128.326, rx=37.0, ry=10.0)
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, pose=pose, hotkeys=hotkeys)
    window.movement.straight_box().setChecked(True)
    window._set_tilt(True)
    window.movement.press_capture()
    hotkeys.press(VK_NUMPAD8)
    assert panel.pose().z == pytest.approx(pose.z + 0.5, abs=0.001)
    assert panel.pose().x == pytest.approx(pose.x, abs=0.001)
    assert panel.pose().y == pytest.approx(pose.y, abs=0.001)


def test_straight_cardinal_uses_the_short_title_in_mini(qt_app: QApplication) -> None:
    """В мини-версии подпись короче: три флажка с полными подписями не влезали в окно."""
    window, _panel, _store, _cursor = make_window(qt_app)
    window.set_mini(True)
    assert window.movement.straight_box().text() == "Прямой шаг"
    window.set_mini(False)
    assert window.movement.straight_box().text() == "Прямой шаг 4/6/8/2"


def test_straight_cardinal_changes_the_tilt_warning(qt_app: QApplication) -> None:
    """Подсказка про наклон говорит, что предмет пойдёт строго вверх."""
    pose = Pose(x=1850.0, y=1850.0, z=128.326, rx=37.0)
    window, _panel, _store, _cursor = make_window(qt_app, pose=pose)
    window.movement.press_capture()
    assert "нажмите Alt" in window.movement.warning_text()
    window.movement.straight_box().setChecked(True)
    assert "строго вверх" in window.movement.warning_text()


def test_straight_cardinal_keeps_pose_and_history(qt_app: QApplication) -> None:
    """Переключение режима — настройка, а не новые координаты: поза и история целы."""
    window, _panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.arrow(Direction.FORWARD).click()
    window.movement.straight_box().setChecked(True)
    assert window.history().can_undo
    assert window.undo()


def test_mode_line_lists_every_active_mode(qt_app: QApplication) -> None:
    """Строка режима перечисляет всё, что включено: высота, прямой шаг или оба.

    «Прямой шаг 4/6/8/2» меняет смысл клавиш не меньше, чем режим высоты, а подпись
    раньше говорила только про высоту — включённый прямой шаг был невидим.
    """
    window, _panel, _store, _cursor = make_window(qt_app)
    movement = window.movement
    assert movement.mode_text() == "8/2 — вперёд/назад"

    movement.set_straight(True)
    assert movement.mode_text() == "Включено: прямой шаг"

    movement.set_tilt(True)
    assert movement.mode_text() == "Включено: высота · прямой шаг"

    movement.set_straight(False)
    assert movement.mode_text() == "Включено: высота"

    movement.set_tilt(False)
    assert movement.mode_text() == "8/2 — вперёд/назад"


def test_settings_skip_own_check_toggles_the_grace(qt_app: QApplication) -> None:
    """Флажок «Не сверять панель сразу после своей записи» задаёт паузу доверия."""
    window, _panel, _store, _cursor = make_window(qt_app)
    tab = window.settings_tab
    assert tab.collect().self_write_grace == 2.0
    tab._skip_own_check.setChecked(False)
    assert tab.collect().self_write_grace == 0.0
    tab._skip_own_check.setChecked(True)
    assert tab.collect().self_write_grace == 2.0


@pytest.mark.parametrize("points", [9.0, 11.0, 14.0, 18.0])
def test_content_is_reachable_at_every_windows_scale(qt_app: QApplication, points: float) -> None:
    """При 100–200 % ничего не уезжает за край: либо помещается, либо листается.

    Windows на 125–200 % увеличивает шрифт и все отступы. Раньше окно оставалось
    эталонных 820 пикселей, и низ вкладки просто обрезался; в мини-версии третьему
    переключателю не хватало 43 пикселей. Теперь окно дорастает по высоте, а если экран
    меньше содержимого — вкладка листается колесом, то есть до любого поля можно дойти.
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QScrollArea

    base_font = qt_app.font()
    font = QFont(base_font.family())
    font.setPointSizeF(points)
    qt_app.setFont(font)
    window: MainWindow | None = None
    try:
        window, _panel, _store, _cursor = make_window(
            qt_app, size_store=FakeSizeStore(_long_library())
        )
        window.show()
        window.set_mini(False)
        qt_app.processEvents()
        qt_app.processEvents()

        def reachable(index: int) -> bool:
            area = window._tabs.widget(index) if window is not None else None
            if not isinstance(area, QScrollArea):
                return True
            return window.tab_fits_height(index) or area.verticalScrollBar().isVisible()

        for index, title in enumerate(window.tab_titles()):
            window.select_tab(index)
            qt_app.processEvents()
            assert window.tab_fits(index), f"«{title}» шире окна при {points} пт"
            assert reachable(index), f"«{title}» не достать по высоте при {points} пт"

        window.press_mini()
        qt_app.processEvents()
        qt_app.processEvents()
        assert window.tab_fits(0), f"мини-версия шире окна при {points} пт"
        assert window.tab_fits_height(0), (
            f"в мини-версии низ крестовины за краем при {points} пт: " f"окно {window.height()} px"
        )
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            qt_app.processEvents()
        qt_app.setFont(base_font)


def test_spin_box_values_are_readable(qt_app: QApplication) -> None:
    """Значение в счётчике видно: поле ввода не сжато до полоски в пиксель.

    Общая таблица стилей рисовала счётчики, но не их стрелки, и Qt считала, что поле
    ввода занимает ноль места: «Знаков после запятой», «Шаг по умолчанию» и «Длина» с
    «Шириной» показывали пустые рамки — число было, а прочитать его было нельзя.
    """
    from map_overlay.ui import theme

    # Таблица стилей — часть дефекта: без неё счётчики выглядят нормально.
    qt_app.setStyleSheet(theme.APP_QSS)
    window: MainWindow | None = None
    try:
        window, _panel, _store, _cursor = make_window(qt_app)
        window.show()
        window.select_tab(3)
        qt_app.processEvents()
        spins = [
            window.settings_tab._click,
            window.settings_tab._decimals,
            window.settings_tab._default_step,
        ]
        window.select_tab(1)
        qt_app.processEvents()
        spins += [window.sizes._length, window.sizes._width]
        for spin in spins:
            edit = spin.lineEdit()
            text_width = edit.fontMetrics().horizontalAdvance(edit.text())
            assert edit.width() >= max(text_width, 20), (edit.text(), edit.width())
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            qt_app.processEvents()
        qt_app.setStyleSheet("")
