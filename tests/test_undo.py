"""Отмена и повтор шагов предмета: Ctrl+Z / Ctrl+Y и история на 20 шагов.

История — только про сдвиги по координатам. Правки библиотеки, настроек и калибровки
не отменяются: заказчик попросил вернуть предмет, а не среду приложения.
"""

from __future__ import annotations

import pytest
from map_overlay.application.history import HISTORY_LIMIT, Change, History
from map_overlay.domain.actions import DEFAULT_HOTKEYS, Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.keynames import VK_DECIMAL
from map_overlay.domain.movement import shifted
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from fakes import FakeSizeStore
from test_ui import START, make_window


def _press(window: object, key: Qt.Key, *, shift: bool = False) -> None:
    """Послать окну нажатие с Ctrl (как это делает пользователь)."""
    modifiers = Qt.KeyboardModifier.ControlModifier
    if shift:
        modifiers |= Qt.KeyboardModifier.ShiftModifier
    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers)
    window.keyPressEvent(event)  # type: ignore[attr-defined]


def _step(window: object, direction: Direction = Direction.FORWARD) -> None:
    """Сделать один шаг стрелкой (шаг по умолчанию — 0.5 м)."""
    window.movement.arrow(direction).click()  # type: ignore[attr-defined]


# --- сама история ---------------------------------------------------------


def test_history_keeps_last_step_for_undo() -> None:
    """Стопка отдаёт последний шаг и сдвигается только по команде."""
    history = History()
    history.record(Change("шаг «Вперёд» на 0.5 м", lambda: True, lambda: True))
    assert history.can_undo
    assert not history.can_redo
    change = history.peek_undo()
    assert change is not None
    assert change.label == "шаг «Вперёд» на 0.5 м"
    # Пока запись в панель не подтвердилась, стопки не сдвигаются.
    assert history.can_undo
    assert history.commit_undo() is change
    assert not history.can_undo
    assert history.can_redo
    assert history.commit_redo() is change
    assert history.can_undo


def test_history_keeps_only_last_twenty_steps() -> None:
    """Помним ровно 20 шагов: двадцать первый вытесняет самый старый."""
    history = History()
    for index in range(HISTORY_LIMIT + 1):
        history.record(Change(f"шаг {index}", lambda: True, lambda: True))
    assert len(history) == HISTORY_LIMIT
    assert history.undo_label == f"шаг {HISTORY_LIMIT}"
    labels = []
    while history.can_undo:
        labels.append(history.commit_undo().label)  # type: ignore[union-attr]
    assert labels[0] == f"шаг {HISTORY_LIMIT}"
    assert labels[-1] == "шаг 1"
    assert "шаг 0" not in labels


def test_new_step_clears_redo() -> None:
    """После свежего шага повторять отменённое нельзя."""
    history = History()
    history.record(Change("первый", lambda: True, lambda: True))
    history.commit_undo()
    assert history.can_redo
    history.record(Change("второй", lambda: True, lambda: True))
    assert not history.can_redo
    assert history.commit_redo() is None


def test_history_limit_must_be_positive() -> None:
    """Нулевой предел — ошибка конфигурации, а не тихое «ничего не помним»."""
    with pytest.raises(ValueError, match="положительным"):
        History(0)


def test_clear_forgets_everything() -> None:
    """Новый «Считать» начинает историю заново."""
    history = History()
    history.record(Change("шаг", lambda: True, lambda: True))
    history.clear()
    assert not history.can_undo
    assert not history.can_redo


# --- окно: шаги предмета --------------------------------------------------


def test_undo_returns_object_to_previous_coordinates(qt_app: QApplication) -> None:
    """Ctrl+Z возвращает предмет туда, где он стоял до шага."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window, Direction.FORWARD)
    moved = panel.pose()
    assert moved != START

    assert window.undo()
    assert panel.pose() == START
    assert panel.values[Field.X] == f"{START.x:.3f}"
    assert "Отменён шаг «Вперёд» на 0.5 м" in window.status_text()


def test_redo_repeats_the_step(qt_app: QApplication) -> None:
    """Ctrl+Y повторяет шаг: предмет встаёт туда же, где был после шага."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window, Direction.LEFT)
    moved = panel.pose()

    window.undo()
    assert panel.pose() == START
    assert window.redo()
    assert panel.pose() == moved
    assert "Повторён шаг «Влево» на 0.5 м" in window.status_text()


def test_undo_keeps_angles(qt_app: QApplication) -> None:
    """Отменяется сдвиг, а не поворот: углы остаются как были."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window, Direction.FORWARD_RIGHT)
    window.undo()
    assert panel.pose().rx == pytest.approx(START.rx)
    assert panel.pose().ry == pytest.approx(START.ry)
    assert panel.pose().rz == pytest.approx(START.rz)


def test_undo_works_for_alt_step(qt_app: QApplication) -> None:
    """Шаг в режиме высоты тоже отменяется: Z возвращается."""
    from dataclasses import replace

    from fakes import FakeHotkeySource
    from test_ui import NUMPAD8, toggle_tilt

    initial = replace(START, rx=45.0)
    hotkeys = FakeHotkeySource()
    window, panel, _store, _cursor = make_window(qt_app, hotkeys=hotkeys, pose=initial)
    window.movement.press_capture()
    toggle_tilt(hotkeys)
    hotkeys.press(NUMPAD8)
    hotkeys.release(NUMPAD8)
    raised = panel.pose()
    assert raised.z > initial.z

    assert window.undo()
    assert panel.pose() == initial


def test_undo_without_capture_is_explained(qt_app: QApplication) -> None:
    """Без «Считать» отменять нечего — так и говорим."""
    window, _panel, _store, _cursor = make_window(qt_app)
    assert not window.undo()
    assert "Сначала нажмите «Считать»" in window.status_text()


def test_undo_without_steps_is_explained(qt_app: QApplication) -> None:
    """Шагов не было — в строке состояния появляется понятный ответ."""
    window, _panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    assert not window.undo()
    assert "Отменять нечего" in window.status_text()
    assert not window.redo()
    assert "Повторять нечего" in window.status_text()


def test_new_capture_forgets_steps(qt_app: QApplication) -> None:
    """После нового «Считать» история шагов начинается заново: старые координаты не наши."""
    window, _panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window)
    window.movement.press_capture()

    assert not window.undo()
    assert "Отменять нечего" in window.status_text()


def test_settings_and_library_are_not_undoable(qt_app: QApplication) -> None:
    """Правки среды приложения не отменяются: Ctrl+Z — только про шаги."""
    store = FakeSizeStore()
    window, _panel, _store, _cursor = make_window(qt_app, size_store=store)
    window.movement.press_capture()
    window.sizes.fill_form("Ящик", 2.0, 1.0)
    window.sizes.press_add()
    window.sizes.press_delete("Ящик")
    window.settings_tab._decimals.setValue(5)
    window.settings_tab._save()
    window.calibration.capture_now(Field.X)

    assert not window.undo()
    assert store.library.items == ()
    assert window._context.settings.decimals == 5
    assert window._context.settings.calibration[Field.X] == Point(100, 200)


def test_failed_undo_keeps_the_step(qt_app: QApplication) -> None:
    """Неудачная отмена не съедает шаг: повторить попытку можно."""
    window, _panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    history = window.history()
    history.record(Change("шаг «Вперёд» на 0.5 м", lambda: False, lambda: False))

    assert not window.undo()
    assert history.can_undo
    assert len(history) == 1
    assert not history.can_redo


def test_undo_itself_is_not_recorded(qt_app: QApplication) -> None:
    """Отмена не попадает в историю как новый шаг."""
    window, _panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window)
    assert len(window.history()) == 1

    window.undo()
    assert len(window.history()) == 0
    assert window.history().can_redo


def test_window_remembers_only_twenty_steps(qt_app: QApplication) -> None:
    """В окне тоже 20 шагов: двадцать первый вытесняет первый."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    for _ in range(HISTORY_LIMIT + 1):
        _step(window, Direction.FORWARD)
    assert len(window.history()) == HISTORY_LIMIT

    while window.history().can_undo:
        window.undo()
    # Первый шаг отменить уже нельзя: предмет остался на месте после него.
    assert panel.pose() == shifted(START, Direction.FORWARD, 0.5)
    assert not window.undo()


# --- клавиши --------------------------------------------------------------


def test_ctrl_z_and_ctrl_y_work_from_keyboard(qt_app: QApplication) -> None:
    """Ctrl+Z и Ctrl+Y работают как клавиши, а не только как методы окна."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window)
    moved = panel.pose()

    _press(window, Qt.Key.Key_Z)
    assert panel.pose() == START
    _press(window, Qt.Key.Key_Y)
    assert panel.pose() == moved
    _press(window, Qt.Key.Key_Z)
    assert panel.pose() == START
    _press(window, Qt.Key.Key_Z, shift=True)
    assert panel.pose() == moved


def test_ctrl_z_in_text_field_edits_text_not_steps(qt_app: QApplication) -> None:
    """В поле ввода Ctrl+Z правит текст: шаг не отменяется."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window)
    moved = panel.pose()

    window.show()
    window._tabs.setCurrentIndex(1)
    window.activateWindow()
    window.sizes._name.setFocus()
    qt_app.processEvents()
    assert window.sizes._name.hasFocus()

    _press(window, Qt.Key.Key_Z)
    assert panel.pose() == moved
    assert window.history().can_undo


# --- вставка координат в другой предмет -----------------------------------

OTHER = Pose(x=310.5, y=-12.25, z=4.5, rx=15.0, ry=90.0, rz=30.0)
# Другой предмет: и позиция, и углы отличаются от START.


def _show_object(panel: object, pose: Pose) -> None:
    """Открыть в панели другой предмет (как будто пользователь выбрал его в игре)."""
    values = panel.values  # type: ignore[attr-defined]
    for field in Field:
        values[field] = f"{pose.value(field):.3f}"


def test_paste_button_copies_the_captured_pose(qt_app: QApplication) -> None:
    """«Вставить» переписывает координаты и углы считанного предмета в получателя."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _show_object(panel, OTHER)
    window.movement.press_paste()
    assert panel.pose() == START
    assert "Вставлено" in window.status_text()


def test_paste_goes_to_the_current_object_not_the_captured_one(qt_app: QApplication) -> None:
    """Кнопка пишет в тот предмет, что открыт сейчас: старый «Считать» не мешает."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _step(window, Direction.FORWARD)
    moved = panel.pose()
    _show_object(panel, OTHER)
    window.movement.press_paste()
    assert panel.pose() == moved
    assert panel.pose() != OTHER


def test_paste_is_undone_with_ctrl_z(qt_app: QApplication) -> None:
    """Ctrl+Z возвращает получателя на прежнее место — вместе с углами."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _show_object(panel, OTHER)
    window.movement.press_paste()
    assert panel.pose() == START

    assert window.undo()
    assert panel.pose() == OTHER
    assert "Отменён перенос координат" in window.status_text()


def test_paste_is_repeated_with_ctrl_y(qt_app: QApplication) -> None:
    """Ctrl+Y повторяет вставку: источник запоминается, а не берётся из текущей позы."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _show_object(panel, OTHER)
    window.movement.press_paste()
    window.undo()
    assert panel.pose() == OTHER

    assert window.redo()
    assert panel.pose() == START
    assert "Повторён перенос координат" in window.status_text()


def test_paste_without_capture_asks_to_read(qt_app: QApplication) -> None:
    """Пока координаты не считаны, вставлять нечего: панель не трогаем."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_paste()
    assert "Считать" in window.status_text()
    assert panel.writes == []


def test_paste_does_not_press_f(qt_app: QApplication) -> None:
    """Вставка только пишет поля: положение подтверждает сам пользователь."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _show_object(panel, OTHER)
    window.movement.press_paste()
    assert panel.confirm_calls == 0


def test_paste_hotkey_is_num_dot(qt_app: QApplication) -> None:
    """Горячая клавиша «Вставить» по умолчанию — Num ."""
    assert DEFAULT_HOTKEYS[Action.PASTE] == VK_DECIMAL
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    _show_object(panel, OTHER)
    window._on_hotkey(VK_DECIMAL, True, True)
    assert panel.pose() == START


def test_paste_button_waits_for_capture(qt_app: QApplication) -> None:
    """До «Считать» кнопка «Вставить» выключена: нажимать нечего."""
    window, _panel, _store, _cursor = make_window(qt_app)
    button = window.movement.paste_button()
    assert not button.isEnabled()
    window.movement.press_capture()
    assert button.isEnabled()
    window.movement.set_pose(None)
    assert not button.isEnabled()


def test_paste_with_identical_pose_writes_nothing(qt_app: QApplication) -> None:
    """Получатель уже стоит там же — панель не трогаем, в статусе так и сказано."""
    window, panel, _store, _cursor = make_window(qt_app)
    window.movement.press_capture()
    window.movement.press_paste()
    assert panel.writes == []
    assert "писать нечего" in window.status_text()
