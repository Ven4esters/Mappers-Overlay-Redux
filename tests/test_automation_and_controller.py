from __future__ import annotations

import ctypes
from pathlib import Path
import py_compile
import sys

import pytest

from mapper_assist.automation import AutomationError, InputBackend, PanelAutomator, WIN32_INPUT
from mapper_assist.config_store import ConfigStore
from mapper_assist.controller import MapperController
from mapper_assist.hotkeys import MOD_ALT, MOD_NOREPEAT, parse_hotkey_spec
from mapper_assist.models import (
    CALIBRATION_TARGETS,
    AppSettings,
    CalibrationProfile,
    MacroTimings,
    Transform,
)


class FakeLspPanelBackend(InputBackend):
    """
    Полная эмуляция левой NUI-панели Los Santos Project:
      - 6 полей ввода по координатам экрана;
      - выделение через Ctrl+A, копирование Ctrl+C, вставка Ctrl+V;
      - фиксация (сохранение) только при клике в нейтральную область вне полей и нажатии Enter.
    """

    FIELD_COORDS = {
        "x": (120, 210),
        "y": (120, 250),
        "z": (120, 290),
        "rx": (120, 330),
        "ry": (120, 370),
        "rz": (120, 410),
    }
    NEUTRAL_COORD = (120, 150)

    def __init__(self, initial_fields: dict[str, str]) -> None:
        self.fields = dict(initial_fields)
        self.saved_snapshot: dict[str, str] | None = None
        self.cursor = (850, 540)
        self.clipboard = "МОЙ_ВАЖНЫЙ_ТЕКСТ_В_БУФЕРЕ"
        self.focused_field: str | None = None
        self.selected_all = False
        self.clicked_Field_history: list[str] = []
        self.enter_pressed_count = 0

        self._coord_to_name = {pt: name for name, pt in self.FIELD_COORDS.items()}

    def make_calibration(self) -> CalibrationProfile:
        cal = CalibrationProfile()
        for name, (px, py) in self.FIELD_COORDS.items():
            cal.set_point(name, px, py)
        cal.set_point("neutral", *self.NEUTRAL_COORD)
        return cal

    def get_cursor_pos(self) -> tuple[int, int]:
        return self.cursor

    def set_cursor_pos(self, x: int, y: int) -> None:
        self.cursor = (int(x), int(y))

    def left_click(self, x: int, y: int) -> None:
        self.cursor = (int(x), int(y))
        self.selected_all = False
        if (x, y) in self._coord_to_name:
            fname = self._coord_to_name[(x, y)]
            self.focused_field = fname
            self.clicked_Field_history.append(fname)
        elif (x, y) == self.NEUTRAL_COORD:
            self.focused_field = None
            self.clicked_Field_history.append("neutral")
        else:
            self.focused_field = None
            self.clicked_Field_history.append("other")

    def send_ctrl_Combo(self, letter: str) -> None:
        ch = letter.upper()
        if ch == "A" and self.focused_field is not None:
            self.selected_all = True
        elif ch == "C" and self.focused_field is not None and self.selected_all:
            self.clipboard = self.fields[self.focused_field]
        elif ch == "V" and self.focused_field is not None:
            if self.selected_all:
                self.fields[self.focused_field] = self.clipboard
                self.selected_all = False

    def send_enter(self) -> None:
        self.enter_pressed_count += 1
        # В меню LSP сохранение срабатывает, когда фокус снят с инпута (кликнули мимо поля)
        if self.focused_field is None:
            self.saved_snapshot = dict(self.fields)

    def wait_modifiers_released(self, timeout_ms: int = 320) -> None:
        pass

    def ensure_window_at_point_focused(
        self,
        x: int,
        y: int,
        neutral_point: tuple[int, int] | None,
        settle_ms: int,
    ) -> None:
        pass

    def get_clipboard(self) -> str:
        return self.clipboard

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text


FAST_TIMINGS = MacroTimings(
    click_delay_ms=1,
    key_delay_ms=1,
    focus_handoff_ms=2,
    clipboard_timeout_ms=60,
    save_enter_delay_ms=1,
)


def test_full_capture_dirty_write_and_save_workflow() -> None:
    fake_nui = FakeLspPanelBackend(
        {
            "x": "250.5",
            "y": "-810.25",
            "z": "31.0",
            "rx": "0",
            "ry": "0",
            "rz": "37.42",
        }
    )
    cal = fake_nui.make_calibration()
    automator = PanelAutomator(backend=fake_nui)

    settings = AppSettings(step=1.0, calibration=cal, timings=FAST_TIMINGS)
    ctrl = MapperController(settings)

    # 1. Захват из панели игры
    captured = automator.read_transform(cal, FAST_TIMINGS)
    ctrl.set_captured_transform(captured)

    assert captured.x == pytest.approx(250.5)
    assert captured.y == pytest.approx(-810.25)
    assert captured.rz == pytest.approx(37.42)
    # Буфер обмена и позиция мыши игрока сохранены нетронутыми!
    assert fake_nui.clipboard == "МОЙ_ВАЖНЫЙ_ТЕКСТ_В_БУФЕРЕ"
    assert fake_nui.cursor == (850, 540)

    # 2. Поворот на +90°: должен измениться и прокликаться ТОЛЬКО RZ!
    fake_nui.clicked_Field_history.clear()
    dirty_rot = ctrl.rotate_by(90.0)
    assert dirty_rot == ["rz"]

    written = automator.write_fields(
        ctrl.current,
        dirty_rot,
        cal,
        FAST_TIMINGS,
        save_with_enter=False,
        verify=False,
    )
    ctrl.mark_synced(written)
    assert fake_nui.clicked_Field_history == ["rz"]
    assert float(fake_nui.fields["rz"]) == pytest.approx(127.42)
    assert fake_nui.saved_snapshot is None  # Enter ещё не нажимали

    # 3. Сдвиг Вправо на 1.0 м: меняются ТОЛЬКО X и Y!
    fake_nui.clicked_Field_history.clear()
    dirty_move = ctrl.move_step(right_sign=1.0)
    assert dirty_move == ["x", "y"]

    written_move = automator.write_fields(
        ctrl.current,
        dirty_move,
        cal,
        FAST_TIMINGS,
        save_with_enter=False,
        verify=False,
    )
    ctrl.mark_synced(written_move)
    assert fake_nui.clicked_Field_history == ["x", "y"]

    # 4. Финальное сохранение «Клик мимо поля + Enter» (всё разом!)
    automator.commit_save_only(cal, FAST_TIMINGS)
    assert fake_nui.enter_pressed_count == 1
    assert fake_nui.saved_snapshot is not None
    assert float(fake_nui.saved_snapshot["rz"]) == pytest.approx(127.42)
    assert fake_nui.cursor == (850, 540)
    assert fake_nui.clipboard == "МОЙ_ВАЖНЫЙ_ТЕКСТ_В_БУФЕРЕ"


def test_missing_calibration_raises_clear_error() -> None:
    fake_nui = FakeLspPanelBackend({"x": "0", "y": "0", "z": "0", "rx": "0", "ry": "0", "rz": "0"})
    empty_cal = CalibrationProfile()
    automator = PanelAutomator(backend=fake_nui)

    with pytest.raises(AutomationError, match="Не откалиброваны точки экрана"):
        automator.read_transform(empty_cal, FAST_TIMINGS)


def test_undo_redo_and_conveyor_advance() -> None:
    ctrl = MapperController(AppSettings(step=0.5, prop_size=2.0))
    ctrl.set_captured_transform(Transform(x=10.0, y=20.0, z=5.0, rz=0.0))
    ctrl.save_reference_from_current()

    # Первая пристыкованная секция вправо (+2.0 м)
    dirty1 = ctrl.join_section_from_reference("right", 0.0)
    assert len(dirty1) == 6
    assert ctrl.current.x == pytest.approx(12.0)

    # Вторая пристыкованная секция конвейером автоматически встаёт на +4.0 м!
    ctrl.join_section_from_reference("right", 0.0)
    assert ctrl.current.x == pytest.approx(14.0)

    # Undo возвращает на 12.0, Redo снова на 14.0
    ctrl.undo()
    assert ctrl.current.x == pytest.approx(12.0)
    ctrl.redo()
    assert ctrl.current.x == pytest.approx(14.0)


def test_config_store_roundtrip(tmp_path: Path) -> None:
    cfg_file = tmp_path / "test_config.json"
    store = ConfigStore(cfg_file)

    s = AppSettings(step=0.25, anchor_rz=-42.75, auto_save_enter=True)
    for idx, t in enumerate(CALIBRATION_TARGETS):
        s.calibration.set_point(t, 100 + idx * 10, 200 + idx * 15)

    store.save(s)
    loaded = store.load()
    assert loaded.step == pytest.approx(0.25)
    assert loaded.anchor_rz == pytest.approx(-42.75)
    assert loaded.auto_save_enter is True
    assert loaded.calibration.is_full_ready()
    assert loaded.calibration.get_point("neutral").to_tuple() == (160, 290)  # type: ignore[union-attr]


def test_hotkey_parser_and_win32_struct_size() -> None:
    parsed = parse_hotkey_spec("Alt+Right")
    assert parsed is not None
    mods, vk = parsed
    assert mods == (MOD_NOREPEAT | MOD_ALT)
    assert vk == 0x27

    assert parse_hotkey_spec("F9") == (MOD_NOREPEAT, 0x78)
    assert parse_hotkey_spec("") is None
    assert parse_hotkey_spec("InvalidKeyName") is None

    # На 64-битной платформе sizeof(WIN32_INPUT) в Windows обязан быть ровно 40 байт
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(WIN32_INPUT) == 40


def test_all_python_files_compile_cleanly() -> None:
    root = Path(__file__).resolve().parent.parent
    py_files = [p for p in root.rglob("*.py") if ".venv" not in p.parts]
    assert len(py_files) >= 10
    for path in py_files:
        py_compile.compile(str(path), doraise=True)


class BrokenPasteBackend(FakeLspPanelBackend):
    """Панель, которая «проглатывает» Ctrl+V: объект в игре остаётся прежним."""

    def send_ctrl_Combo(self, letter: str) -> None:  # noqa: N802
        if letter.upper() == "V":
            return
        super().send_ctrl_Combo(letter)


def test_write_is_verified_and_catches_lost_paste() -> None:
    fake_nui = BrokenPasteBackend(
        {"x": "10", "y": "20", "z": "5", "rx": "0", "ry": "0", "rz": "0"}
    )
    cal = fake_nui.make_calibration()
    automator = PanelAutomator(backend=fake_nui)

    target = Transform(x=99.0, y=20.0, z=5.0, rz=0.0)
    with pytest.raises(AutomationError, match="не применились"):
        automator.write_fields(target, ["x"], cal, FAST_TIMINGS)

    # Значение в «игре» не изменилось, и курсор/буфер возвращены владельцу
    assert float(fake_nui.fields["x"]) == 10.0
    assert fake_nui.cursor == (850, 540)
    assert fake_nui.clipboard == "МОЙ_ВАЖНЫЙ_ТЕКСТ_В_БУФЕРЕ"


def test_write_verification_passes_on_healthy_panel() -> None:
    fake_nui = FakeLspPanelBackend(
        {"x": "10", "y": "20", "z": "5", "rx": "0", "ry": "0", "rz": "0"}
    )
    cal = fake_nui.make_calibration()
    automator = PanelAutomator(backend=fake_nui)

    target = Transform(x=10.5, y=20.0, z=5.0, rz=0.0)
    written = automator.write_fields(target, ["x"], cal, FAST_TIMINGS)  # verify=True по умолчанию
    assert written == ["x"]
    assert float(fake_nui.fields["x"]) == pytest.approx(10.5)


def test_direction_inversion_flags() -> None:
    settings = AppSettings(step=1.0)
    ctrl = MapperController(settings)
    ctrl.set_captured_transform(Transform(x=0.0, y=0.0, z=0.0, rz=0.0))

    ctrl.move_step(forward_sign=1.0)
    assert ctrl.current.y == pytest.approx(1.0)

    settings.invert_forward = True
    ctrl.move_step(forward_sign=1.0)
    assert ctrl.current.y == pytest.approx(0.0)

    settings.invert_right = True
    ctrl.move_step(right_sign=1.0)
    assert ctrl.current.x == pytest.approx(-1.0)

    settings.invert_rotate = True
    ctrl.rotate_by(90.0)
    assert ctrl.current.rz == pytest.approx(-90.0)


def test_settings_persist_direction_and_safety_flags(tmp_path) -> None:
    store = ConfigStore(tmp_path / "cfg.json")
    settings = AppSettings(
        invert_forward=True,
        invert_right=True,
        invert_up=True,
        invert_rotate=True,
        safe_write_verify=False,
        max_jump=42.5,
    )
    store.save(settings)
    loaded = store.load()
    assert loaded.invert_forward and loaded.invert_right
    assert loaded.invert_up and loaded.invert_rotate
    assert loaded.safe_write_verify is False
    assert loaded.max_jump == pytest.approx(42.5)
