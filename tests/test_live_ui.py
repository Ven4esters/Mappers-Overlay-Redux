"""Живой режим и Numpad в окне: копия едет, F сам не нажимается, клавиши не утекают."""

from __future__ import annotations

import time
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

from fakes import FakeGamePanel, FakeKeyHook, FakeKeyState, build_calibration  # noqa: E402
from test_keymap import press_key, release_key  # noqa: E402

START = Pose(x=250.5, y=-810.25, z=31.0, rz=0.0)
NUMPAD_8_VK = 0x68
SETTLE = 0.35


def make_window(
    tmp_path: Path,
    qt_app: object,
    *,
    pose: Pose = START,
    settings: Settings | None = None,
    keys: FakeKeyState | None = None,
    hook: FakeKeyHook | None = None,
) -> tuple[OverlayWindow, FakeGamePanel, FakeKeyState, FakeKeyHook]:
    settings = settings or Settings(calibration=build_calibration())
    panel = FakeGamePanel(pose)
    panel.configure(
        calibration=settings.calibration,
        timings=settings.timings,
        length_decimals=settings.length_decimals,
        confirm_key=settings.confirm_key,
    )
    session = MappingSession(panel, settings)
    state = keys or FakeKeyState()
    key_hook = hook or FakeKeyHook()
    window = OverlayWindow(
        session,
        ConfigStore(tmp_path / "settings.json"),
        settings,
        key_state=state,
        key_hook=key_hook,
    )
    window.action_capture()
    return window, panel, state, key_hook


def pump(app: object, seconds: float) -> None:
    """Крутит цикл событий Qt: без него не тикают таймеры повтора и живого режима."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()  # type: ignore[attr-defined]
        time.sleep(0.005)


def wait_until(condition: object, app: object, timeout: float = 2.0) -> None:
    """Ждёт выполнения условия, не забывая обрабатывать события Qt."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()  # type: ignore[attr-defined]
        if condition():  # type: ignore[operator]
            return
        time.sleep(0.005)
    raise AssertionError("условие не выполнилось за отведённое время")


def test_live_mode_clones_and_moves_the_copy(tmp_path: Path, qt_app: object) -> None:
    """Включение живого режима клонирует предмет и двигает копию в игре."""
    window, panel, _keys, _hook = make_window(tmp_path, qt_app)
    window.movement_tab.btn_live.setChecked(True)
    try:
        assert panel.keys == ["c"]
        assert window._live.is_running
        window.movement_tab.move_requested.emit(Direction.NORTH.value, 0.5)
        wait_until(lambda: panel.pose.y >= START.y + 0.5 - 1e-6, qt_app)
    finally:
        window.movement_tab.btn_live.setChecked(False)
    assert panel.commits == 0, "живой режим не должен сам нажимать F"
    assert not window._live.is_running


def test_live_mode_commits_only_with_setting(tmp_path: Path, qt_app: object) -> None:
    """Галочка «Подтверждать F в живом режиме» включает подтверждение каждого шага."""
    settings = Settings(calibration=build_calibration(), live_commit=True)
    window, panel, _keys, _hook = make_window(tmp_path, qt_app, settings=settings)
    window.movement_tab.btn_live.setChecked(True)
    try:
        window.movement_tab.move_requested.emit(Direction.NORTH.value, 0.5)
        wait_until(lambda: panel.commits >= 1, qt_app)
    finally:
        window.movement_tab.btn_live.setChecked(False)


def test_hooked_numpad_moves_the_copy_and_releases(tmp_path: Path, qt_app: object) -> None:
    """Хук забирает Numpad у игры: нажатие ведёт копию, отпускание её останавливает."""
    window, panel, _keys, hook = make_window(tmp_path, qt_app)
    window.movement_tab.btn_live.setChecked(True)
    try:
        hook.press(NUMPAD_8_VK)  # Numpad 8
        wait_until(lambda: panel.writes, qt_app)
        assert panel.keys == ["c"]
        hook.release(NUMPAD_8_VK)
        pump(qt_app, SETTLE)
        moved = panel.pose.y
        pump(qt_app, SETTLE)
        assert panel.pose.y == pytest.approx(moved), "после отпускания объект должен стоять"
    finally:
        window.movement_tab.btn_live.setChecked(False)
    assert hook.callback is None, "хук должен быть снят"


def test_live_mode_stops_when_clone_key_fails(tmp_path: Path, qt_app: object) -> None:
    """Панель недоступна — живой режим не включается и кнопка возвращается в исходное."""
    window, panel, _keys, _hook = make_window(tmp_path, qt_app)
    panel.available = False
    window.movement_tab.btn_live.setChecked(True)
    assert window.movement_tab.btn_live.isChecked() is False
    assert not window._live.is_running
    assert "недоступна" in window.lbl_status.text()


def test_num_lock_off_is_reported(tmp_path: Path, qt_app: object) -> None:
    """Без NumLock Numpad шлёт другие клавиши — об этом надо сказать сразу."""
    window, _panel, _keys, _hook = make_window(tmp_path, qt_app, keys=FakeKeyState(num_lock=False))
    window.movement_tab.btn_live.setChecked(True)
    try:
        assert "NumLock выключен" in window.lbl_status.text()
    finally:
        window.movement_tab.btn_live.setChecked(False)


def test_numpad_without_live_mode_moves_the_overlay_only(tmp_path: Path, qt_app: object) -> None:
    """Без живого режима Numpad двигает только оверлей: в игру пишет «Применить»."""
    window, panel, _keys, _hook = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    release_key(window, Qt.Key.Key_8)
    assert window.movement_tab.editors[FieldKey.Y].value() == pytest.approx(-810.15)
    assert panel.writes == []
    assert "ΔY +0.100" in window.lbl_status.text()


def test_numpad_zero_captures_and_plus_scales_step(tmp_path: Path, qt_app: object) -> None:
    """Numpad 0 — «Считать», «+»/«−» — шаг."""
    window, _panel, _keys, _hook = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_Plus)
    release_key(window, Qt.Key.Key_Plus)
    assert window.movement_tab.current_step() == pytest.approx(0.2)
    press_key(window, Qt.Key.Key_Minus)
    release_key(window, Qt.Key.Key_Minus)
    assert window.movement_tab.current_step() == pytest.approx(0.1)
    press_key(window, Qt.Key.Key_0)
    release_key(window, Qt.Key.Key_0)
    assert window.lbl_status.text().startswith("Считано")


def test_held_numpad_repeats_and_stops_after_release(tmp_path: Path, qt_app: object) -> None:
    """Удержание = плавное движение, отпускание = стоп."""
    window, _panel, _keys, _hook = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    pump(qt_app, SETTLE)
    moved = window.movement_tab.editors[FieldKey.Y].value()
    assert moved > START.y + 0.15, "за полсекунды должно пройти больше одного шага"
    release_key(window, Qt.Key.Key_8)
    pump(qt_app, SETTLE)
    assert window.movement_tab.editors[FieldKey.Y].value() == pytest.approx(moved)


def test_close_window_stops_live_and_removes_hook(tmp_path: Path, qt_app: object) -> None:
    """Закрытие окна не оставляет хук за игрой."""
    window, _panel, _keys, hook = make_window(tmp_path, qt_app)
    window.movement_tab.btn_live.setChecked(True)
    window.close()
    assert hook.callback is None
    assert not window._live.is_running
