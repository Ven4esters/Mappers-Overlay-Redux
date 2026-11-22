"""Дымовые тесты интерфейса: окно собирается и кнопки делают то, что обещают."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", reason="PySide6 недоступен")

from lsp_overlay.application.session import MappingSession  # noqa: E402
from lsp_overlay.config import Settings  # noqa: E402
from lsp_overlay.domain.catalog import Catalog, Dimension, ObjectSpec  # noqa: E402
from lsp_overlay.domain.directions import Direction  # noqa: E402
from lsp_overlay.domain.fields import FieldKey  # noqa: E402
from lsp_overlay.domain.movement import MoveSpace  # noqa: E402
from lsp_overlay.domain.pose import Pose  # noqa: E402
from lsp_overlay.infrastructure.catalog_store import CatalogStore  # noqa: E402
from lsp_overlay.infrastructure.config_store import ConfigStore  # noqa: E402
from lsp_overlay.ui.overlay import OverlayWindow  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import (
    QFocusEvent,  # noqa: E402
    QGuiApplication,  # noqa: E402
)

from fakes import FakeGamePanel, build_calibration  # noqa: E402
from test_keymap import press_key, release_key  # noqa: E402

START = Pose(x=250.5, y=-810.25, z=31.0, rz=0.0)


def make_window(
    tmp_path: Path, qt_app: object, *, pose: Pose = START
) -> tuple[OverlayWindow, FakeGamePanel]:
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(pose)
    panel.configure(
        calibration=settings.calibration,
        timings=settings.timings,
        length_decimals=settings.length_decimals,
        confirm_key=settings.confirm_key,
    )
    session = MappingSession(panel, settings)
    window = OverlayWindow(
        session,
        ConfigStore(tmp_path / "settings.json"),
        settings,
        catalog_store=CatalogStore(tmp_path / "objects.json"),
    )
    window.action_capture()
    return window, panel


def test_window_has_seven_tabs(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert titles == [
        "Движение",
        "Повороты",
        "Рулетка",
        "Объекты",
        "Стык",
        "Калибровка",
        "Настройки",
    ]


def test_join_places_second_object_without_pressing_f(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Стена", length=4.0, width=2.5, thickness=0.2))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    window.join_tab.place_requested.emit()
    assert panel.commits == 0
    assert panel.pose.x == pytest.approx(250.5 + 2.1)
    assert panel.pose.y == pytest.approx(-810.25 + 1.9)
    assert panel.pose.rz == pytest.approx(-90.0)
    assert "без F" in window.lbl_status.text() or "F не нажат" in window.lbl_status.text()


def test_join_45_button_sets_angle(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.join_tab.btn_45.click()
    assert window.join_tab.request().angle == pytest.approx(45.0)
    assert window.join_tab.btn_45.isChecked()
    assert not window.join_tab.btn_90.isChecked()


def test_join_tee_disables_angle_controls(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.join_tab.radio_tee.setChecked(True)
    assert not window.join_tab.spin_angle.isEnabled()
    assert not window.join_tab.btn_45.isEnabled()
    assert window.join_tab.request().scheme.value == "tee"


def test_join_swap_makes_second_object_the_base(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Стена", length=4.0, width=0.2, thickness=3.0))
    window.action_save_object(ObjectSpec(name="Забор", length=2.0, width=0.1, thickness=2.0))
    first = window.join_tab.selected_specs()[0]
    second = window.join_tab.selected_specs()[1]
    window.action_swap_join_objects()
    assert window.join_tab.selected_specs()[0] == second
    assert window.join_tab.selected_specs()[1] == first


def test_join_requires_capture_first(tmp_path: Path, qt_app: object) -> None:
    """Без «Считать» стык не ставится: неизвестно, где стоит A."""
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(Pose(x=100.0, y=200.0, z=30.0, rz=25.0))
    window = OverlayWindow(
        MappingSession(panel, settings), ConfigStore(tmp_path / "s.json"), settings
    )
    window.action_save_object(ObjectSpec(name="Стена", length=4.0, width=2.5, thickness=0.2))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    window.join_tab.place_requested.emit()
    assert not panel.writes
    assert "Считать" in window.lbl_status.text()


def test_join_keeps_captured_base_even_if_panel_shows_other_object(
    tmp_path: Path, qt_app: object
) -> None:
    """В панели после «Считать» стоит B — стык всё равно идёт от A."""
    window, panel = make_window(
        tmp_path, qt_app, pose=Pose(x=-1847.342, y=420.077, z=128.316, rz=70.0)
    )
    window.action_capture()
    panel.pose = Pose(x=-1847.792, y=413.718, z=128.456, rz=0.0)
    window.action_save_object(ObjectSpec(name="Стена March", length=2.73, width=2.5, thickness=0.0))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    window.join_tab.place_requested.emit()
    assert "угол A 70.0° → B -20.0°" in window.lbl_status.text()
    assert panel.pose.x == pytest.approx(-1848.158, abs=1e-3)


def test_join_can_reread_panel_pose_by_checkbox(tmp_path: Path, qt_app: object) -> None:
    """Галочка «Перечитывать A из панели» включает явное чтение."""
    window, panel = make_window(tmp_path, qt_app, pose=Pose(x=1.0, y=2.0, z=3.0, rz=0.0))
    window.action_capture()
    panel.pose = Pose(x=1.0, y=2.0, z=3.0, rz=70.0)
    window.action_save_object(ObjectSpec(name="Стена", length=4.0, width=2.5, thickness=0.2))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    assert not window.join_tab.refresh_base()
    assert "из последнего «Считать»" in window.join_tab.base_line()
    window.join_tab.chk_refresh.setChecked(True)
    assert "перечитан из панели" in window.join_tab.base_line()
    window.join_tab.place_requested.emit()
    assert "угол A 70.0° → B -20.0°" in window.lbl_status.text()


def test_join_tab_shows_base_angle_and_across_value(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app, pose=Pose(x=1.0, y=2.0, z=3.0, rz=70.0))
    window.action_save_object(ObjectSpec(name="Стена", length=4.0, width=2.5, thickness=0.2))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    assert "угол 70.0°" in window.join_tab.base_line()
    assert window.join_tab.across_text() == "0.200 м"
    assert "поперёк" in window.join_tab.shift_text()
    assert "вдоль длины" in window.join_tab.shift_text()
    window.join_tab.place_requested.emit()
    assert "угол A 70.0° → B -20.0°" in window.lbl_status.text()


def test_join_without_dimensions_reports_error(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Точка"))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    window.join_tab.place_requested.emit()
    assert "длина" in window.lbl_status.text()
    assert panel.writes == []


def test_capture_fills_coordinate_editors(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    assert window.movement_tab.editors[FieldKey.X].value() == pytest.approx(250.5)
    assert window.movement_tab.editors[FieldKey.RZ].value() == pytest.approx(0.0)


def test_move_button_updates_pose_and_marks_pending(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    assert window.movement_tab.editors[FieldKey.Y].value() == pytest.approx(-809.25)
    assert window.btn_apply.isEnabled()


def test_arrow_pad_has_exactly_eight_directions(tmp_path: Path, qt_app: object) -> None:
    """В крестовине только план: 8 направлений, кнопок высоты нет."""
    from PySide6.QtWidgets import QPushButton

    window, _panel = make_window(tmp_path, qt_app)
    buttons = [
        button
        for button in window.movement_tab.findChildren(QPushButton)
        if button.objectName() == "arrowButton"
    ]
    assert len(buttons) == 8
    labels = {button.text() for button in buttons}
    assert labels == {"↖", "↑", "↗", "←", "→", "↙", "↓", "↘"}


def test_apply_writes_to_game_and_commits(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 0.5)
    window.action_apply(commit=True)
    assert panel.pose.y == pytest.approx(-809.75)
    assert panel.commits == 1
    assert "Записано" in window.lbl_status.text()


def test_jump_guard_reports_error(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_move(Direction.SOUTH.value, 100.0)
    assert window.lbl_status.property("level") == "error"
    assert "лимита" in window.lbl_status.text()


def test_rotate_tab_turns_yaw(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.rotate_tab.rotate_requested.emit("rz", 90.0)
    assert window.movement_tab.editors[FieldKey.RZ].value() == pytest.approx(90.0)


def test_calibration_tab_shows_points(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.calibration_tab.set_calibration(build_calibration())
    assert window.calibration_tab.lbl_placeholder.text() == "900, 900"
    assert window.calibration_tab.calibration.is_complete


def test_mini_mode_hides_tabs(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.btn_mini.click()
    assert window.tabs.isHidden()
    window.btn_mini.click()
    assert not window.tabs.isHidden()


def test_settings_saved_applies_opacity_and_persists(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    settings = Settings(calibration=build_calibration(), confirm_key="f", overlay_opacity=1.0)
    window.action_settings_saved(settings)
    assert window.windowOpacity() == pytest.approx(1.0)
    assert (tmp_path / "settings.json").exists()


def test_move_status_shows_where_the_prop_went(tmp_path: Path, qt_app: object) -> None:
    """После шага видно, по каким осям, с каким углом и на сколько сдвинулся предмет."""
    window, _panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=70.0))
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    text = window.lbl_status.text()
    assert "по углу предмета, RZ 70.0°" in text
    assert "ΔX -0.940" in text
    assert "ΔY +0.342" in text


def test_sideways_button_writes_both_axes_when_prop_is_turned(
    tmp_path: Path, qt_app: object
) -> None:
    """При угле 70° кнопка «влево» пишет и X, и Y — предмет едет ровно поперёк."""
    window, panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=70.0))
    window.movement_tab.move_requested.emit(Direction.WEST.value, 1.0)
    text = window.lbl_status.text()
    assert "ΔX -0.342" in text
    assert "ΔY -0.940" in text
    window.action_apply(commit=False)
    assert panel.pose.x == pytest.approx(-0.342, abs=1e-3)
    assert panel.pose.y == pytest.approx(-0.940, abs=1e-3)


def test_frame_hint_shows_the_numbers_for_a_sideways_step(tmp_path: Path, qt_app: object) -> None:
    """Подсказка показывает, что шаг вбок задевает обе оси."""
    window, _panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=70.0))
    text = window.movement_tab.frame_text()
    assert "Оси: предмет (угол 70.0° · с наклонами RX/RY)" in text
    assert "← ΔX -0.34 · ΔY -0.94" in text
    assert "по X и Y сразу" in text


def test_anchor_button_takes_current_angle(tmp_path: Path, qt_app: object) -> None:
    """«Взять из предмета» запоминает угол как якорь комнаты и сохраняет его."""
    window, _panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=70.0))
    window.action_take_anchor()
    assert window._settings.anchor_rz == pytest.approx(70.0)
    assert window.movement_tab.anchor_text() == "70°"
    assert "Якорь комнаты: 70°" in window.lbl_status.text()
    saved = Settings.from_dict(__import__("json").loads((tmp_path / "settings.json").read_text()))
    assert saved.anchor_rz == pytest.approx(70.0)


def test_anchor_frame_is_shown_in_the_hint(tmp_path: Path, qt_app: object) -> None:
    """Режим «якорь» пишет в подсказку свой угол, а не угол предмета."""
    window, _panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=20.0))
    tab = window.settings_tab
    tab.spin_anchor.setValue(70.0)
    tab.combo_frame.setCurrentIndex(tab.combo_frame.findData(MoveSpace.ANCHOR.value))
    window.action_settings_saved(tab._collect())  # noqa: SLF001 - проверяем саму вкладку
    assert "Оси: якорь комнаты (70.0°)" in window.movement_tab.frame_text()
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    assert "по якорю комнаты, 70.0°" in window.lbl_status.text()


def test_direction_fix_checkboxes_mirror_the_step(tmp_path: Path, qt_app: object) -> None:
    """Поправка «↑ вперёд» зеркалит шаг и видна в строке состояния."""
    window, panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=0.0))
    tab = window.settings_tab
    tab._invert_boxes["forward"].setChecked(True)  # noqa: SLF001 - проверяем саму вкладку
    window.action_settings_saved(tab._collect())  # noqa: SLF001 - проверяем саму вкладку
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    assert "направления поправлены" in window.lbl_status.text()
    window.action_apply(commit=False)
    assert panel.pose.y == pytest.approx(-1.0)


def test_tilt_checkbox_is_on_like_the_first_release(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    assert window.settings_tab.chk_tilt.isChecked() is True


def test_camera_buttons_work_only_in_world_frame(tmp_path: Path, qt_app: object) -> None:
    """Кнопки поправки на камеру нужны только в осях мира, в осях предмета они выключены."""
    window, _panel = make_window(tmp_path, qt_app)
    assert window.movement_tab.camera_controls_enabled() is False
    tab = window.settings_tab
    tab.combo_frame.setCurrentIndex(tab.combo_frame.findData(MoveSpace.WORLD.value))
    window.action_settings_saved(tab._collect())  # noqa: SLF001 - проверяем саму вкладку
    assert window.movement_tab.camera_controls_enabled() is True


def test_movement_frame_hint_follows_settings(tmp_path: Path, qt_app: object) -> None:
    """Подсказка под крестовиной говорит, в каких осях ходят стрелки."""
    window, _panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=70.0))
    window.action_capture()
    assert "Оси: предмет" in window.movement_tab.frame_text()
    tab = window.settings_tab
    tab.combo_frame.setCurrentIndex(tab.combo_frame.findData(MoveSpace.WORLD.value))
    window.action_settings_saved(tab._collect())  # noqa: SLF001 - проверяем саму вкладку
    assert window._settings.move_frame is MoveSpace.WORLD
    assert "Оси: мир" in window.movement_tab.frame_text()
    assert "Угол детали не учитывается" in window.movement_tab.frame_text()


def test_camera_correction_aligns_arrows(tmp_path: Path, qt_app: object) -> None:
    """«Поворот осей» 45°: ↑ уводит на северо-запад, и это видно в подсказке."""
    window, panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=70.0))
    window.action_capture()
    tab = window.settings_tab
    tab.combo_frame.setCurrentIndex(tab.combo_frame.findData(MoveSpace.WORLD.value))
    tab.spin_rotation.setValue(45.0)
    window.action_settings_saved(tab._collect())  # noqa: SLF001 - проверяем саму вкладку
    assert window._settings.move_rotation == pytest.approx(45.0)
    assert "повёрнуты на 45°" in window.movement_tab.frame_text()
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    assert "ΔX -0.707" in window.lbl_status.text()
    window.action_apply(commit=False)
    assert panel.pose.x == pytest.approx(-0.7071, abs=1e-3)
    assert panel.pose.y == pytest.approx(0.7071, abs=1e-3)


def test_camera_buttons_turn_axes_by_45(tmp_path: Path, qt_app: object) -> None:
    """Кнопки «Камера» крутят оси на 45° и сразу сохраняют настройку."""
    window, panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=0.0))
    window.action_capture()
    tab = window.settings_tab
    tab.combo_frame.setCurrentIndex(tab.combo_frame.findData(MoveSpace.WORLD.value))
    window.action_settings_saved(tab._collect())  # noqa: SLF001 - проверяем саму вкладку
    assert window.movement_tab.rotation_text() == "0°"
    window.action_turn_move_axes(-45.0)
    assert window._settings.move_rotation == pytest.approx(-45.0)
    assert window.movement_tab.rotation_text() == "-45°"
    assert "повёрнуты на -45°" in window.movement_tab.frame_text()
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    window.action_apply(commit=False)
    assert panel.pose.x == pytest.approx(0.7071, abs=1e-3)
    assert panel.pose.y == pytest.approx(0.7071, abs=1e-3)
    saved = Settings.from_dict(__import__("json").loads((tmp_path / "settings.json").read_text()))
    assert saved.move_rotation == pytest.approx(-45.0)


def test_live_commit_checkbox_toggles_confirmation(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    tab = window.settings_tab
    assert tab.chk_live_commit.isChecked() is False
    tab.chk_live_commit.setChecked(True)
    window.action_settings_saved(tab._collect())  # noqa: SLF001 - проверяем саму вкладку
    assert window._settings.live_commit is True
    assert window._live.commit is True
    window.action_live_toggled(True)
    try:
        press_key(window, Qt.Key.Key_8)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and panel.commits == 0:
            qt_app.processEvents()  # type: ignore[attr-defined]
            time.sleep(0.01)
        release_key(window, Qt.Key.Key_8)
        assert panel.commits >= 1
    finally:
        window.action_live_toggled(False)
    assert window._settings.live_commit is True


def test_apply_without_capture_shows_error(tmp_path: Path, qt_app: object) -> None:
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(START)
    window = OverlayWindow(
        MappingSession(panel, settings), ConfigStore(tmp_path / "s.json"), settings
    )
    window.movement_tab.move_requested.emit(Direction.NORTH.value, 1.0)
    window.action_apply(commit=True)
    assert "Считать" in window.lbl_status.text()


def test_join_switches_across_to_width(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Плита", length=4.0, width=2.5, thickness=0.1))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    window.join_tab.place_requested.emit()
    assert panel.pose.x == pytest.approx(250.5 + 0.05 + 2.0)
    assert panel.pose.y == pytest.approx(-810.25 + 2.0 - 0.05)
    panel.pose = START  # возвращаем A на место: следующая попытка — снова от A
    window.action_capture()
    index = window.join_tab.combo_across.findData("width")
    window.join_tab.combo_across.setCurrentIndex(index)
    window.join_tab.place_requested.emit()
    assert panel.pose.x == pytest.approx(250.5 + 1.25 + 2.0)


def test_across_choices_show_values(tmp_path: Path, qt_app: object) -> None:
    """В списке «Поперёк» видны значения габаритов, а не только названия."""
    window, _panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Стена March", length=2.73, width=2.5, thickness=0.1))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    texts = [window.join_tab.combo_across.itemText(index) for index in range(2)]
    assert texts[0] == "Толщина · 0.100 м"
    assert texts[1] == "Ширина · 2.500 м"


def test_join_refuses_width_when_it_is_the_height(tmp_path: Path, qt_app: object) -> None:
    """Ширина 2.5 при неизмеренной толщине — стык не ставится, есть подсказка."""
    window, panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Стена March", length=2.73, width=2.5, thickness=0.0))
    window.join_tab.combo_first.setCurrentIndex(0)
    window.join_tab.combo_second.setCurrentIndex(0)
    window.join_tab.combo_across.setCurrentIndex(window.join_tab.combo_across.findData("width"))
    window.join_tab.place_requested.emit()
    assert not panel.writes
    assert "ширина это высота" in window.lbl_status.text()


def test_dimension_labels_in_objects_tab_have_thickness(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    headers = [
        window.objects_tab.table.horizontalHeaderItem(index).text()
        for index in range(window.objects_tab.table.columnCount())
    ]
    assert headers == ["Название", "Длина", "Ширина", "Толщина"]


def test_height_is_editable_through_z_field(tmp_path: Path, qt_app: object) -> None:
    """Кнопок высоты нет, но Z по-прежнему можно задать вручную."""
    window, panel = make_window(tmp_path, qt_app)
    window.action_field_edited(FieldKey.Z.value, 31.75)
    window.action_apply(commit=True)
    assert panel.pose.z == pytest.approx(31.75)


def test_measurement_along_wrong_axis_is_not_recorded(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=70.0))
    window.action_remember_point("a")
    panel.pose = Pose(x=2.52, y=-0.91, z=0.0, rz=70.0)
    window.action_remember_point("b")
    window.action_measure_dimension("width")
    assert "другой оси" in window.lbl_status.text()
    assert window.objects_tab.dimension_text(Dimension.WIDTH) == "—"


def test_measure_tab_shows_dimensions_for_the_line(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    panel.pose = Pose(x=252.5, y=-806.25, z=31.0)
    window.action_remember_point("b")
    text = window.measure_tab.projection_text()
    assert "длина 4.000 м" in text
    assert "ширина 2.000 м" in text


def test_diagnostics_reports_success(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.calibration_tab.diagnostics_requested.emit()
    assert window.lbl_status.property("level") == "success"
    assert "Ввод работает" in window.lbl_status.text()


def test_diagnostics_reports_broken_write(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    panel.ignore_fields = {FieldKey.X}
    window.action_diagnostics()
    assert window.lbl_status.property("level") == "error"
    assert "администратора" in window.lbl_status.text()


def test_measure_tab_shows_object_length(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    assert window.measure_tab.value_text("distance") == "—"
    window.movement_tab.field_edited.emit(FieldKey.X.value, START.x + 4.5)
    window.action_apply(commit=False)
    window.action_remember_point("b")
    assert window.measure_tab.value_text("planar") == "4.500 м"
    assert window.measure_tab.value_text("heading") == "90.0°"


def test_measure_step_becomes_shift_step(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.Y.value, START.y + 2.0)
    window.action_apply(commit=False)
    window.action_remember_point("b")
    window.measure_tab.step_requested.emit(2.0)
    assert window.movement_tab.current_step() == pytest.approx(2.0)
    assert window._settings.step == pytest.approx(2.0)


def test_measure_reset_clears_points(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    window.measure_tab.reset_requested.emit()
    assert window.measure_tab.point_text("a") == "—"


def test_measure_step_button_waits_for_two_points(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    assert not window.measure_tab.btn_step.isEnabled()
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.X.value, START.x + 3.0)
    window.action_apply(commit=False)
    window.action_remember_point("b")
    assert window.measure_tab.btn_step.isEnabled()


def test_measure_copy_puts_text_on_clipboard(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.X.value, START.x + 1.0)
    window.action_apply(commit=False)
    window.action_remember_point("b")
    window.measure_tab.btn_copy.click()
    assert "Замер" in window.measure_tab.result_text()
    assert QGuiApplication.clipboard().text() == window.measure_tab.result_text()


def test_numpad_moves_prop_forward(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    assert window._session.pose.y == pytest.approx(START.y + 0.1)
    assert window._session.pending_fields() == (FieldKey.Y,)


def test_numpad_diagonal_moves_two_axes(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_9)
    half = 0.1 / 2**0.5
    assert window._session.pose.x == pytest.approx(START.x + half)
    assert window._session.pose.y == pytest.approx(START.y + half)


def test_numpad_five_saves_changes(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_6)
    press_key(window, Qt.Key.Key_5)
    assert panel.pose.x == pytest.approx(START.x + 0.1)
    assert panel.commits == 1


def test_numpad_enter_applies_without_confirm(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_6)
    press_key(window, Qt.Key.Key_Enter)
    assert panel.pose.x == pytest.approx(START.x + 0.1)
    assert panel.commits == 0


def test_numpad_plus_doubles_step(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_Plus)
    assert window.movement_tab.current_step() == pytest.approx(0.2)


def test_plain_arrow_does_nothing(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8, Qt.KeyboardModifier.NoModifier)
    assert window._session.pending_fields() == ()


def measure_fence(window: OverlayWindow) -> None:
    """Меряет длину 4.5 м вдоль локальной оси Y и записывает её в габарит."""
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.Y.value, START.y + 4.5)
    window.action_apply(commit=False)
    window.action_remember_point("b")
    window.action_measure_dimension(Dimension.LENGTH.value)


def test_measure_dimension_writes_length_in_local_axes(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    measure_fence(window)
    assert window.objects_tab.dimension_text(Dimension.LENGTH) == "4.500 м"
    assert window.lbl_status.property("level") == "success"


def test_measure_dimension_respects_rotation(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app, pose=Pose(x=0.0, y=0.0, z=0.0, rz=90.0))
    window.action_remember_point("a")
    window.movement_tab.field_edited.emit(FieldKey.X.value, 4.5)
    window.action_apply(commit=False)
    window.action_remember_point("b")
    window.action_measure_dimension(Dimension.LENGTH.value)
    assert window.objects_tab.dimension_text(Dimension.LENGTH) == "4.500 м"


def test_measure_dimension_needs_two_points(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_measure_dimension(Dimension.WIDTH.value)
    assert window.objects_tab.dimension_text(Dimension.WIDTH) == "—"
    assert window.lbl_status.property("level") == "warning"


def test_object_saved_to_table_and_file(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    measure_fence(window)
    window.objects_tab.edit_name.setText("Забор бетонный")
    window.objects_tab.btn_save.click()
    assert window.objects_tab.table.rowCount() == 1
    assert window.objects_tab.table.item(0, 0).text() == "Забор бетонный"
    assert window.objects_tab.table.item(0, 1).text() == "4.50 м"
    raw = (tmp_path / "objects.json").read_text(encoding="utf-8")
    assert "Забор бетонный" in raw
    assert window.objects_tab.dimension_text(Dimension.LENGTH) == "—"


def test_object_search_filters_table(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    for name, length in (("Забор бетонный", 4.5), ("Барьер", 2.0)):
        window.action_save_object(ObjectSpec(name=name, length=length))
    assert window.objects_tab.table.rowCount() == 2
    window.objects_tab.edit_search.setText("бар")
    assert window.objects_tab.table.rowCount() == 1
    assert window.objects_tab.table.item(0, 0).text() == "Барьер"


def test_object_step_from_table(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Забор", length=4.5, width=0.25, thickness=1.2))
    assert window.objects_tab.select_name("Забор")
    window.objects_tab.btn_step.click()
    assert window.movement_tab.current_step() == pytest.approx(4.5)


def test_object_delete_removes_row_and_file(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    window.action_save_object(ObjectSpec(name="Забор", length=4.5))
    assert window.objects_tab.select_name("Забор")
    window.objects_tab.btn_delete.click()
    assert window.objects_tab.table.rowCount() == 0
    assert "Забор" not in (tmp_path / "objects.json").read_text(encoding="utf-8")


def test_objects_are_loaded_on_start(tmp_path: Path, qt_app: object) -> None:
    store = CatalogStore(tmp_path / "objects.json")
    store.save(Catalog().upsert(ObjectSpec(name="Забор", length=4.5)))
    window, _panel = make_window(tmp_path, qt_app)
    assert window.objects_tab.table.rowCount() == 1


def test_remember_button_reads_coordinates_itself(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    panel.pose = Pose(x=1.0, y=2.0, z=3.0)
    window.action_remember_point("a")
    assert window.measure_tab.point_text("a") == "1.00, 2.00, 3.00"
    assert panel.reads >= 2


def test_numpad_hold_repeats_movement(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    assert window._session.pose.y == pytest.approx(START.y + 0.1)
    window._repeat_tick()
    window._repeat_tick()
    assert window._session.pose.y == pytest.approx(START.y + 0.3)


def test_numpad_release_stops_repeat(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    release_key(window, Qt.Key.Key_8)
    window._repeat_tick()
    assert window._session.pose.y == pytest.approx(START.y + 0.1)


def test_numpad_flashes_arrow_button(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    assert window.movement_tab._direction_buttons[Direction.NORTH].isDown()
    release_key(window, Qt.Key.Key_8)
    assert not window.movement_tab._direction_buttons[Direction.NORTH].isDown()


def test_numpad_step_keys_do_not_move(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_Plus)
    assert window._session.pending_fields() == ()


def test_live_mode_clones_and_applies_in_game(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.action_live_toggled(True)
    try:
        assert panel.keys == ["c"]
        assert window._live.is_running
        press_key(window, Qt.Key.Key_8)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not panel.writes:
            qt_app.processEvents()  # type: ignore[attr-defined]
            time.sleep(0.01)
        release_key(window, Qt.Key.Key_8)
        assert panel.writes
        assert panel.commits == 0
        assert panel.pose.y > START.y
    finally:
        window.action_live_toggled(False)
    assert not window._live.is_running
    assert window.lbl_status.text().startswith("Живой режим выключен")


def test_live_mode_arrow_button_moves_one_step(tmp_path: Path, qt_app: object) -> None:
    """Клик мышью по стрелке — один шаг, а не бесконечное движение."""
    window, panel = make_window(tmp_path, qt_app)
    window.action_live_toggled(True)
    try:
        window.movement_tab.move_requested.emit(Direction.NORTH.value, 0.5)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not panel.writes:
            time.sleep(0.01)
        assert panel.writes
        assert window._live.direction is None
        steps = window._live.applied
        time.sleep(0.3)
        assert window._live.applied == steps
    finally:
        window.action_live_toggled(False)


def test_live_mode_stops_when_numpad_release_is_lost(tmp_path: Path, qt_app: object) -> None:
    window, panel, hook = make_window_with_hook(tmp_path, qt_app)
    window.action_live_toggled(True)
    window._live.set_hold_timeout(0.05)
    try:
        hook.press(0x68)  # Numpad 8, отпускание «потерялось»
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not panel.writes:
            time.sleep(0.01)
        time.sleep(0.3)
        steps = window._live.applied
        time.sleep(0.2)
        assert window._live.applied == steps
        assert window._live.direction is None
    finally:
        window.action_live_toggled(False)


def test_live_mode_stops_when_release_is_lost_and_key_is_up(tmp_path: Path, qt_app: object) -> None:
    """Событие отпускания потерялось, но клавиша уже не нажата — сверка состояния гасит шаг."""
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(START)
    keys = FakeKeyState()
    hook = FakeKeyHook()
    window = OverlayWindow(
        MappingSession(panel, settings),
        ConfigStore(tmp_path / "s.json"),
        settings,
        key_state=keys,  # type: ignore[arg-type]
        key_hook=hook,  # type: ignore[arg-type]
    )
    window.action_capture()
    window.action_live_toggled(True)
    try:
        keys.pressed.add(0x68)
        hook.press(0x68)
        assert window._live.direction is Direction.NORTH
        keys.pressed.clear()  # отпускание до оверлея не дошло
        window._poll_live()
        assert window._live.direction is None
    finally:
        window.action_live_toggled(False)


def test_live_mode_keeps_moving_while_key_is_really_down(tmp_path: Path, qt_app: object) -> None:
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(START)
    keys = FakeKeyState()
    hook = FakeKeyHook()
    window = OverlayWindow(
        MappingSession(panel, settings),
        ConfigStore(tmp_path / "s.json"),
        settings,
        key_state=keys,  # type: ignore[arg-type]
        key_hook=hook,  # type: ignore[arg-type]
    )
    window.action_capture()
    window.action_live_toggled(True)
    window._live.set_hold_timeout(0.05)
    try:
        keys.pressed.add(0x68)
        hook.press(0x68)
        for _ in range(6):
            time.sleep(0.04)
            window._poll_live()  # сверка продлевает удержание
        assert window._live.direction is Direction.NORTH
        assert window._live.applied >= 1
    finally:
        window.action_live_toggled(False)


def test_live_mode_without_calibration_does_not_start(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    panel.available = False
    window.action_live_toggled(True)
    assert not window._live.is_running
    assert not window.movement_tab.btn_live.isChecked()
    assert window.lbl_status.property("level") == "error"


def test_delete_clone_presses_configured_key(tmp_path: Path, qt_app: object) -> None:
    window, panel = make_window(tmp_path, qt_app)
    window.action_delete_clone()
    assert panel.keys == ["delete"]


class FakeKeyState:
    """Глобальное состояние клавиш для живого режима."""

    def __init__(self) -> None:
        self.pressed: set[int] = set()

    def is_ready(self) -> bool:
        return True

    def is_down(self, vk_code: int) -> bool:
        return vk_code in self.pressed

    def num_lock_enabled(self) -> bool:
        return True


def make_window_with_keys(
    tmp_path: Path, qt_app: object
) -> tuple[OverlayWindow, FakeGamePanel, object]:
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(START)
    panel.configure(
        calibration=settings.calibration,
        timings=settings.timings,
        length_decimals=settings.length_decimals,
        confirm_key=settings.confirm_key,
    )
    session = MappingSession(panel, settings)
    keys = FakeKeyState()
    window = OverlayWindow(
        session,
        ConfigStore(tmp_path / "settings.json"),
        settings,
        catalog_store=CatalogStore(tmp_path / "objects.json"),
        key_state=keys,  # type: ignore[arg-type]
    )
    window.action_capture()
    return window, panel, keys


def test_live_mode_reads_keys_without_window_focus(tmp_path: Path, qt_app: object) -> None:
    window, panel, keys = make_window_with_keys(tmp_path, qt_app)
    window.action_live_toggled(True)
    try:
        keys.pressed.add(0x68)  # Numpad 8
        window._poll_keys()
        assert window._live.direction is Direction.NORTH
        assert window.movement_tab._direction_buttons[Direction.NORTH].isDown()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not panel.writes:
            time.sleep(0.01)
        keys.pressed.clear()
        window._poll_keys()
        assert window._live.direction is None
        assert not window.movement_tab._direction_buttons[Direction.NORTH].isDown()
        assert panel.writes
        assert panel.commits == 0
    finally:
        window.action_live_toggled(False)


class FakeKeyHook:
    """Глобальный хук клавиш для тестов."""

    def __init__(self) -> None:
        self.callback: object = None
        self.started = 0
        self.stopped = 0

    def is_available(self) -> bool:
        return True

    def start(self, callback: object) -> bool:
        self.callback = callback
        self.started += 1
        return True

    def stop(self) -> None:
        self.stopped += 1
        self.callback = None

    def press(self, vk_code: int) -> None:
        self.callback(vk_code, True)  # type: ignore[operator]

    def release(self, vk_code: int) -> None:
        self.callback(vk_code, False)  # type: ignore[operator]


def make_window_with_hook(
    tmp_path: Path, qt_app: object
) -> tuple[OverlayWindow, FakeGamePanel, FakeKeyHook]:
    settings = Settings(calibration=build_calibration())
    panel = FakeGamePanel(START)
    panel.configure(
        calibration=settings.calibration,
        timings=settings.timings,
        length_decimals=settings.length_decimals,
        confirm_key=settings.confirm_key,
    )
    session = MappingSession(panel, settings)
    hook = FakeKeyHook()
    window = OverlayWindow(
        session,
        ConfigStore(tmp_path / "settings.json"),
        settings,
        catalog_store=CatalogStore(tmp_path / "objects.json"),
        key_hook=hook,  # type: ignore[arg-type]
    )
    window.action_capture()
    return window, panel, hook


def test_live_mode_hooks_numpad_so_game_does_not_see_it(tmp_path: Path, qt_app: object) -> None:
    window, panel, hook = make_window_with_hook(tmp_path, qt_app)
    window.action_live_toggled(True)
    try:
        assert hook.started == 1
        hook.press(0x68)  # Numpad 8
        assert window._live.direction is Direction.NORTH
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not panel.writes:
            time.sleep(0.01)
        hook.release(0x68)
        assert window._live.direction is None
        assert panel.writes
        assert panel.commits == 0
    finally:
        window.action_live_toggled(False)
    assert hook.stopped >= 1


def test_live_mode_ignores_hooked_commands(tmp_path: Path, qt_app: object) -> None:
    window, _panel, hook = make_window_with_hook(tmp_path, qt_app)
    window.action_live_toggled(True)
    try:
        hook.press(0x65)  # Numpad 5 — не направление
        assert window._live.direction is None
    finally:
        window.action_live_toggled(False)


def test_focus_loss_stops_autorepeat(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    window._repeat_timer.start()
    window.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert not window._repeat_timer.isActive()
    window._repeat_tick()
    assert window._session.pose.y == pytest.approx(START.y + 0.1)


def test_autorepeat_stops_when_key_events_are_lost(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    press_key(window, Qt.Key.Key_8)
    window._last_key_time = time.monotonic() - 5.0
    window._repeat_tick()
    assert not window._repeat_timer.isActive()
    assert window._session.pose.y == pytest.approx(START.y + 0.1)


def test_live_guard_stops_runaway(tmp_path: Path, qt_app: object) -> None:
    window, _panel, _hook = make_window_with_hook(tmp_path, qt_app)
    window.action_live_toggled(True)
    window._live.steer(Direction.NORTH, 0.1)
    window._live._applied = 10_000  # type: ignore[attr-defined]
    window._poll_live()
    assert not window._live.is_running
    assert window.lbl_status.property("level") == "error"
    assert not window.movement_tab.btn_live.isChecked()


def test_capture_warns_about_mouse_before_touching_panel(tmp_path: Path, qt_app: object) -> None:
    window, _panel = make_window(tmp_path, qt_app)
    seen: dict[str, str] = {}
    original = window._session.capture

    def spy() -> Pose:
        seen["status"] = window.lbl_status.text()
        return original()

    window._session.capture = spy  # type: ignore[method-assign]
    window.action_capture()
    assert "не двигайте мышь" in seen["status"]
    assert window.lbl_status.text().startswith("Считано")
