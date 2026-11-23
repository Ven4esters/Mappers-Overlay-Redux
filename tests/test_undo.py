"""Отмена и возврат правок: Ctrl+Z / Ctrl+Y и история на 20 действий."""

from __future__ import annotations

import pytest
from map_overlay.application.history import HISTORY_LIMIT, Change, History
from map_overlay.config import Delays, Settings
from map_overlay.domain.actions import Action
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point
from map_overlay.domain.sizes import ObjectSize, SizeLibrary
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from fakes import FakeSizeStore
from test_ui import make_window


def _library(*items: ObjectSize, active: str | None = None) -> SizeLibrary:
    library = SizeLibrary()
    for item in items:
        library = library.with_item(item)
    return library.select(active)


def _press(window: object, key: Qt.Key, *, shift: bool = False) -> None:
    """Послать окну нажатие с Ctrl (как это делает пользователь)."""
    modifiers = Qt.KeyboardModifier.ControlModifier
    if shift:
        modifiers |= Qt.KeyboardModifier.ShiftModifier
    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers)
    window.keyPressEvent(event)  # type: ignore[attr-defined]


# --- сама история ---------------------------------------------------------


def test_history_undoes_and_redoes_last_change() -> None:
    """История возвращает действие назад и повторяет его вперёд."""
    log: list[str] = []
    history = History()
    history.record(
        Change("добавление «Ящик»", lambda: log.append("undo"), lambda: log.append("redo"))
    )
    assert history.can_undo
    assert not history.can_redo
    assert history.undo() == "добавление «Ящик»"
    assert log == ["undo"]
    assert not history.can_undo
    assert history.can_redo
    assert history.redo() == "добавление «Ящик»"
    assert log == ["undo", "redo"]
    assert history.undo_label == "добавление «Ящик»"


def test_history_keeps_only_last_twenty_changes() -> None:
    """Помним ровно 20 действий: двадцать первое вытесняет самое старое."""
    log: list[int] = []
    history = History()
    for index in range(HISTORY_LIMIT + 1):
        history.record(
            Change(
                f"шаг {index}",
                lambda index=index: log.append(index),
                lambda index=index: log.append(-index),
            )
        )
    assert len(history) == HISTORY_LIMIT
    while history.can_undo:
        history.undo()
    # Первое действие вытеснено: вернули 20 последних, а не 21.
    assert log == list(range(20, 0, -1))
    assert not history.can_undo


def test_new_change_clears_redo() -> None:
    """После свежей правки возвращать отменённое нельзя."""
    history = History()
    history.record(Change("первое", lambda: None, lambda: None))
    history.undo()
    assert history.can_redo
    history.record(Change("второе", lambda: None, lambda: None))
    assert not history.can_redo
    assert history.redo() is None


def test_failed_undo_keeps_change_in_history() -> None:
    """Если отмена не удалась, действие не теряется."""

    def boom() -> None:
        message = "файл занят"
        raise ValueError(message)

    history = History()
    history.record(Change("правка", boom, lambda: None))
    with pytest.raises(ValueError, match="файл занят"):
        history.undo()
    assert history.can_undo
    assert not history.can_redo


def test_history_limit_must_be_positive() -> None:
    """Нулевой предел истории — ошибка конфигурации, а не тихое «ничего не помним»."""
    with pytest.raises(ValueError, match="положительным"):
        History(0)


# --- окно: библиотека размеров -------------------------------------------


def test_undo_returns_deleted_item(qt_app: QApplication) -> None:
    """Удалили предмет по ошибке — Ctrl+Z возвращает его вместе с файлом."""
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_delete("Ящик")
    assert store.library.items == ()

    assert window.undo()
    assert [item.name for item in store.library.items] == ["Ящик"]
    assert window.sizes.row_names() == ["Ящик"]
    assert "Отменено: удаление «Ящик»" in window.status_text()

    assert window.redo()
    assert store.library.items == ()
    assert "Возвращено: удаление «Ящик»" in window.status_text()


def test_undo_removes_added_item(qt_app: QApplication) -> None:
    """Добавили не тот предмет — отмена убирает и запись, и строку списка."""
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.fill_form("Ящик", 2.0, 1.0)
    window.sizes.press_add()
    assert [item.name for item in store.library.items] == ["Ящик"]

    assert window.undo()
    assert store.library.items == ()
    assert window.sizes.row_names() == []
    assert "Отменено: добавление «Ящик»" in window.status_text()


def test_undo_restores_previous_name_after_edit(qt_app: QApplication) -> None:
    """Правка названия отменяется целиком: имя и габариты прежние."""
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_pencil("Ящик")
    window.sizes.fill_form("Сундук", 3.0, 0.5)
    window.sizes.press_add()
    assert [item.name for item in store.library.items] == ["Сундук"]

    assert window.undo()
    item = store.library.items[0]
    assert (item.name, item.length, item.width) == ("Ящик", 2.0, 1.0)
    assert "Отменено: правка «Сундук»" in window.status_text()


def test_undo_restores_previous_selection(qt_app: QApplication) -> None:
    """Выбор предмета тоже правка: отмена возвращает прежний текущий предмет."""
    library = _library(
        ObjectSize(name="Ящик", length=2.0, width=1.0),
        ObjectSize(name="Дверь", length=1.0, width=0.2),
        active="Ящик",
    )
    store = FakeSizeStore(library)
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_select("Дверь")
    assert store.library.active == "Дверь"

    assert window.undo()
    assert store.library.active == "Ящик"
    assert window.movement._size_combo.currentText().startswith("Ящик")


# --- окно: настройки и калибровка ----------------------------------------


def test_undo_restores_settings(qt_app: QApplication) -> None:
    """«Сохранить» в настройках отменяется: значения и поля формы возвращаются."""
    store = FakeSizeStore()
    settings = Settings(delays=Delays(click=0.06, select=0.05, copy=0.05, paste=0.08), decimals=3)
    window, _panel, settings_store, _cursor = make_window(
        qt_app, settings=settings, size_store=store
    )
    tab = window.settings_tab
    tab._decimals.setValue(5)
    tab._save()
    assert settings_store.settings.decimals == 5

    assert window.undo()
    assert settings_store.settings.decimals == 3
    assert tab._decimals.value() == 3
    assert "Отменено: настройки" in window.status_text()


def test_undo_restores_calibration_point(qt_app: QApplication) -> None:
    """Точка калибровки отменяется: поле снова прочерк, бейдж серый."""

    window, _panel, store, _cursor = make_window(qt_app)
    window.calibration.capture_now(Field.X)
    assert store.settings.calibration[Field.X] == Point(100, 200)

    assert window.undo()
    assert store.settings.calibration == {}
    assert window.calibration.points() == {}
    assert "Отменено: точка поля X" in window.status_text()
    assert window._calibration_label.property("role") == "badge"

    assert window.redo()
    assert store.settings.calibration[Field.X] == Point(100, 200)


def test_undo_restores_hotkey(qt_app: QApplication) -> None:
    """Снятая привязка возвращается вместе с маршрутом клавиш."""
    window, _panel, store, _cursor = make_window(qt_app)
    assert store.settings.hotkeys[Action.MOVE_FORWARD] is not None

    window._clear_hotkey(Action.MOVE_FORWARD)
    assert store.settings.hotkeys[Action.MOVE_FORWARD] is None

    assert window.undo()
    assert store.settings.hotkeys[Action.MOVE_FORWARD] is not None
    assert "Отменено: снятие клавиши «Вперёд»" in window.status_text()


# --- окно: клавиши и пределы ---------------------------------------------


def test_ctrl_z_and_ctrl_y_work_from_keyboard(qt_app: QApplication) -> None:
    """Ctrl+Z и Ctrl+Y работают как клавиши, а не только как методы окна."""
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_delete("Ящик")

    _press(window, Qt.Key.Key_Z)
    assert [item.name for item in store.library.items] == ["Ящик"]
    _press(window, Qt.Key.Key_Z, shift=True)
    assert store.library.items == ()
    _press(window, Qt.Key.Key_Z)
    assert [item.name for item in store.library.items] == ["Ящик"]
    _press(window, Qt.Key.Key_Y)
    assert store.library.items == ()


def test_ctrl_z_in_text_field_edits_text_not_history(qt_app: QApplication) -> None:
    """В поле ввода Ctrl+Z правит текст: история окна не трогается."""
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_delete("Ящик")
    window.show()
    window._tabs.setCurrentIndex(1)
    window.activateWindow()
    window.sizes._name.setFocus()
    qt_app.processEvents()
    assert window.sizes._name.hasFocus()

    _press(window, Qt.Key.Key_Z)
    assert store.library.items == ()
    assert window.history().can_undo


def test_undo_when_history_is_empty_is_explained(qt_app: QApplication) -> None:
    """Отменять нечего — так и говорим, а не молчим."""
    window, _panel, _settings, _cursor = make_window(qt_app)
    assert not window.undo()
    assert "Отменять нечего" in window.status_text()
    assert not window.redo()
    assert "Возвращать нечего" in window.status_text()


def test_undo_itself_is_not_recorded(qt_app: QApplication) -> None:
    """Отмена не попадает в историю как новое действие, иначе Ctrl+Z зациклился бы."""
    store = FakeSizeStore(_library(ObjectSize(name="Ящик", length=2.0, width=1.0)))
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    window.sizes.press_delete("Ящик")
    assert len(window.history()) == 1

    window.undo()
    assert len(window.history()) == 0
    assert window.history().can_redo
    window.redo()
    assert len(window.history()) == 1


def test_window_remembers_only_twenty_actions(qt_app: QApplication) -> None:
    """В окне тоже 20: двадцать первая правка вытесняет первую."""
    store = FakeSizeStore()
    window, _panel, _settings, _cursor = make_window(qt_app, size_store=store)
    for index in range(HISTORY_LIMIT + 1):
        window.sizes.fill_form(f"Ящик {index}", 2.0, 1.0)
        window.sizes.press_add()
    assert len(window.history()) == HISTORY_LIMIT
    assert len(store.library.items) == HISTORY_LIMIT + 1

    while window.history().can_undo:
        window.undo()
    # Осталось только самое первое добавление: его отменить уже нельзя.
    assert [item.name for item in store.library.items] == ["Ящик 0"]
