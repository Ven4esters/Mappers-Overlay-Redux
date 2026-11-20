"""
Интеграционные smoke-тесты настоящего окна PySide6.

В окружении без графической библиотеки (например, Linux-контейнер без libGL)
тесты автоматически пропускаются; на Windows запускаются по-настоящему.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtWidgets
except ImportError as exc:  # libGL отсутствует в контейнере / Qt не установлен
    pytest.skip(f"PySide6 GUI недоступен в этом окружении: {exc}", allow_module_level=True)

QApplication = QtWidgets.QApplication
QInputDialog = QtWidgets.QInputDialog
QPushButton = QtWidgets.QPushButton

from mapper_assist.automation import PanelAutomator  # noqa: E402
from mapper_assist.config_store import ConfigStore  # noqa: E402
from mapper_assist.controller import MapperController  # noqa: E402
from mapper_assist.models import AppSettings  # noqa: E402
from mapper_assist.ui.main_window import MapperMainWindow  # noqa: E402
from mapper_assist.ui.settings_dialog import SettingsDialog  # noqa: E402
from test_automation_and_controller import FAST_TIMINGS, FakeLspPanelBackend  # noqa: E402

FIELD_DATA = {"x": "250.5", "y": "-810.25", "z": "31.0", "rx": "0.0", "ry": "0.0", "rz": "127.42"}


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtCore import QCoreApplication

    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        pytest.skip("Уже создан QCoreApplication — виджеты Qt в этом процессе недоступны")
    return existing or QApplication([])


def _make_window(qt_app, auto_apply: bool = True, auto_save: bool = False):
    fake = FakeLspPanelBackend(dict(FIELD_DATA))
    settings = AppSettings()
    settings.calibration = fake.make_calibration()
    settings.timings = FAST_TIMINGS
    settings.auto_apply_to_game = auto_apply
    settings.auto_save_enter = auto_save
    settings.hotkeys_enabled = False

    store = ConfigStore(Path(tempfile.mkdtemp(prefix="lspcfg-")) / "user_config.json")
    controller = MapperController(settings)
    window = MapperMainWindow(
        controller=controller,
        config_store=store,
        automator=PanelAutomator(fake),
    )
    window.show()
    qt_app.processEvents()
    return window, fake, settings, store, qt_app


def _pump(app: QApplication, window: MapperMainWindow, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if not window.macro_runner.is_busy:
            app.processEvents()
            return
        time.sleep(0.005)


def test_window_builds_with_three_tabs(qt_app) -> None:
    window, *_ = _make_window(qt_app)
    try:
        assert window.tabs.count() == 3
        assert window.tabs.tabText(0) == "Движение"
        assert window.tabs.tabText(1) == "Стыковка и Линейка"
        assert window.tabs.tabText(2) == "Калибровка"
        assert set(window.field_box.spins) == {"x", "y", "z", "rx", "ry", "rz"}
        assert window.lbl_status.text()
        assert not window.calib_banner_frame.isVisible()
        # компактный оверлей, а не громоздкая панель
        assert window.width() <= 400
        assert window.height() <= 520
    finally:
        window.close()


def test_capture_move_and_commit_save_against_fake_panel(qt_app) -> None:
    window, fake, _settings, _store, app = _make_window(qt_app)
    try:
        window.action_capture_from_game()
        _pump(app, window)
        assert window.controller.current.x == pytest.approx(250.5)
        assert window.controller.current.rz == pytest.approx(127.42)

        window.quick.set_step_value(0.5)
        window.action_move(0.0, 1.0, 0.0)
        _pump(app, window)
        # Вводятся только изменившиеся поля X и Y — RZ и Z не трогаем
        assert "X, Y" in window.lbl_status.text()
        assert fake.fields["rz"] == "127.42"

        window.action_commit_save_in_game()
        _pump(app, window)
        assert fake.enter_pressed_count >= 1
        assert fake.saved_snapshot is not None
    finally:
        window.close()


def test_every_button_is_clickable_without_errors(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Секция 4м", True)))
    # модальный диалог настроек не должен блокировать тест
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: 0)
    window, *_rest, app = _make_window(qt_app)
    try:
        clicked = 0
        # кнопки компактного оверлея
        for button in window.findChildren(QPushButton):
            if button.text() in ("⚙", "▾"):
                continue  # модальные настройки и мини-режим проверяются отдельно
            button.click()
            app.processEvents()
            _pump(app, window, timeout=3.0)
            clicked += 1
        # кнопки окна «Инструменты»
        for index in range(window.tabs.count()):
            page = window.tabs.widget(index)
            for button in page.findChildren(QPushButton):
                if button.text() == "Закрыть":
                    continue
                button.click()
                app.processEvents()
                _pump(app, window, timeout=3.0)
                clicked += 1
        assert clicked > 40, f"Ожидалось много кнопок, нажато: {clicked}"
        assert window.lbl_status.text()
    finally:
        window.close()


def test_calibration_flow_updates_settings_via_window(qt_app) -> None:
    window, fake, settings, _store, app = _make_window(qt_app)
    try:
        window.start_full_calibration()
        app.processEvents()
        assert window.calib_banner_frame.isVisible()

        fake.cursor = (640, 480)
        window.calibration_flow.capture_now()
        app.processEvents()
        captured = settings.calibration.get_point("x")
        assert captured is not None and (captured.x, captured.y) == (640, 480)

        window.calibration_flow.cancel()
        app.processEvents()
        assert not window.calib_banner_frame.isVisible()
        assert not window.calibration_flow.is_active
    finally:
        window.close()


def test_jump_guard_blocks_runaway_object(qt_app) -> None:
    window, fake, settings, _store, app = _make_window(qt_app)
    try:
        window.action_capture_from_game()
        _pump(app, window)
        settings.max_jump = 5.0

        # Ручной ввод координаты на 300 м в стороне — ввод должен быть заблокирован
        window.field_box.spins["x"].setValue(window.controller.current.x + 300.0)
        window._on_manual_field_edited("x")
        app.processEvents()
        _pump(app, window)

        assert "заблокирован" in window.lbl_status.text().lower()
        assert float(fake.fields["x"]) == pytest.approx(250.5)
    finally:
        window.close()


def test_invert_flags_change_movement_direction(qt_app) -> None:
    window, fake, settings, _store, app = _make_window(qt_app)
    try:
        window.action_capture_from_game()
        _pump(app, window)
        window.quick.set_step_value(1.0)

        start = window.controller.current
        window.action_move(0.0, 1.0, 0.0)
        _pump(app, window)
        forward_y = window.controller.current.y
        assert forward_y != pytest.approx(start.y)

        settings.invert_forward = True
        window._sync_ui_from_state()
        window.action_move(0.0, 1.0, 0.0)
        _pump(app, window)
        assert window.controller.current.y == pytest.approx(start.y, abs=1e-6)
    finally:
        window.close()


def test_quick_panel_parses_custom_step(qt_app) -> None:
    window, _fake, settings, _store, app = _make_window(qt_app)
    try:
        window.quick.combo_step.setCurrentText("0,25")
        window.quick._apply_step_from_combo()
        app.processEvents()
        assert settings.step == pytest.approx(0.25)

        window.quick.combo_step.setCurrentText("abc")
        window.quick._apply_step_from_combo()
        app.processEvents()
        assert settings.step == pytest.approx(0.1)  # некорректный ввод не ломает шаг

        window.quick.combo_step.setCurrentText("1000")
        window.quick._apply_step_from_combo()
        app.processEvents()
        assert settings.step == pytest.approx(500.0)  # ограничение сверху
    finally:
        window.close()


def test_mini_mode_and_settings_persistence(qt_app) -> None:
    window, _fake, _settings, store, app = _make_window(qt_app)
    try:
        window._toggle_mini_mode()
        app.processEvents()
        assert not window.body_container.isVisible()
        window._toggle_mini_mode()
        app.processEvents()
        assert window.body_container.isVisible()

        window._save_settings()
        assert store.path.exists()
    finally:
        window.close()
