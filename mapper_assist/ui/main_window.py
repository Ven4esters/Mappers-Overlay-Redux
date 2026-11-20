from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..automation import PanelAutomator
from ..config_store import ConfigStore
from ..controller import MapperController
from ..hotkeys import GlobalHotkeyService
from ..logger import get_logger
from ..models import (
    CALIBRATION_LABELS,
    FIELD_NAMES,
    ROT_FIELDS,
    MoveSpace,
    Transform,
    format_number,
)
from .calibration_flow import CalibrationFlow
from .quick_panel import QuickPanel
from .settings_dialog import SettingsDialog
from .styles import OVERLAY_STYLESHEET
from .threads import HotkeyBridge, MacroRunner
from .tools_dialog import ToolsDialog
from .widgets import CoordinatesBox, make_button, make_label


logger = get_logger("mapper_assist.ui.window")


class MapperMainWindow(QMainWindow):
    """
    Компактный оверлей: только то, что нужно во время маппинга.
      * «Захват» и «Сохранить» — крупными кнопками;
      * 6 координат, крестовина со шагом и три кнопки поворота;
      * всё остальное (оси, якорь, пресеты, стыковка, линейка, калибровка) — в окне «Инструменты».
    """

    def __init__(
        self,
        controller: MapperController | None = None,
        config_store: ConfigStore | None = None,
        automator: PanelAutomator | None = None,
    ) -> None:
        super().__init__()
        self.config_store = config_store or ConfigStore()
        loaded_settings = self.config_store.load()
        self.controller = controller or MapperController(loaded_settings)

        try:
            self.automator = automator or PanelAutomator()
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось инициализировать драйвер ввода Windows — работа в режиме расчёта")
            from ..automation import FallbackInputBackend, PanelAutomator as _PA

            self.automator = _PA(FallbackInputBackend())

        self.hotkey_bridge = HotkeyBridge(self)
        self.hotkey_bridge.triggered.connect(self._on_hotkey_action)

        self.macro_runner = MacroRunner(self)
        self.macro_runner.finished.connect(self._on_macro_finished)
        self.macro_runner.failed.connect(self._on_macro_failed)
        self.macro_runner.busy_changed.connect(self._on_macro_busy)

        self.calibration_flow = CalibrationFlow(
            cursor_provider=self.automator.get_cursor_pos,
            hotkey_name_provider=lambda: self.settings.hotkeys.calibrate_point,
            parent=self,
        )
        self.calibration_flow.banner_text_changed.connect(self.lbl_calib_banner_setText)
        self.calibration_flow.point_captured.connect(self._on_calibration_point)
        self.calibration_flow.finished.connect(self._on_calibration_finished)
        self.calibration_flow.cancelled.connect(self._on_calibration_cancelled)
        self.calibration_flow.active_changed.connect(self._on_calibration_active_changed)

        self._mini_mode = False
        self._pending_rollback: tuple[Transform, list[str]] | None = None

        self.hotkey_service = GlobalHotkeyService(on_action=self.hotkey_bridge.emit_action)

        self._setup_window_flags()
        self._build_ui()
        self._build_tools_dialog()
        self._update_button_hotkey_titles()
        self.setStyleSheet(OVERLAY_STYLESHEET)
        self.setWindowOpacity(self.settings.window_opacity)

        self._sync_ui_from_state()
        self._refresh_calibration_labels()
        self._restart_hotkeys()
        logger.info("Главное окно создано (компактный режим), интерфейс готов")

    # ------------------------------------------------------------------ свойства
    @property
    def settings(self):
        return self.controller.settings

    @property
    def movement(self) -> QuickPanel:
        return self.quick

    @property
    def join_tab(self):
        return self.tools.join_tab

    @property
    def calib_tab(self):
        return self.tools.calibration_tab

    @property
    def tabs(self):
        return self.tools.tabs

    # ------------------------------------------------------------------ окно
    def _setup_window_flags(self) -> None:
        self.setWindowTitle("LSP Mapper Assist")
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        if self.settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setMinimumWidth(330)
        self.setMaximumWidth(380)

    # ------------------------------------------------------------------ сборка UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)

        root.addLayout(self._build_top_bar())
        root.addWidget(self._build_calibration_banner())
        root.addLayout(self._build_main_actions())

        self.body_container = QWidget()
        body = QVBoxLayout(self.body_container)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)

        self.field_box = CoordinatesBox(self.settings.pos_decimals, self.settings.rot_decimals)
        self.field_box.field_edited.connect(self._on_manual_field_edited)
        body.addWidget(self.field_box)

        self.quick = QuickPanel(self.settings)
        self.quick.move_requested.connect(self.action_move)
        self.quick.rotate_requested.connect(self.action_rotate_yaw)
        self.quick.step_changed.connect(self._on_step_changed)
        body.addWidget(self.quick)
        root.addWidget(self.body_container)

        self.lbl_status = make_label("Готов. Откалибруйте поля панели: «Инструменты» → «Калибровка».")
        self.lbl_status.setObjectName("statusBanner")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

    def _small_button(self, text: str, tooltip: str) -> QPushButton:
        button = make_button(text, tooltip)
        button.setObjectName("btnSmall")
        button.setMinimumHeight(24)
        return button

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(4)

        self.btn_pin = self._small_button("Поверх", "Держать окно поверх FiveM (нужен режим «окно без рамки»)")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(self.settings.always_on_top)
        self.btn_pin.clicked.connect(self._toggle_always_on_top)
        bar.addWidget(self.btn_pin)

        self.btn_hk_toggle = self._small_button("Клавиши", "Включить/отключить глобальные горячие клавиши")
        self.btn_hk_toggle.setCheckable(True)
        self.btn_hk_toggle.setChecked(self.settings.hotkeys_enabled)
        self.btn_hk_toggle.clicked.connect(self._toggle_hotkeys)
        bar.addWidget(self.btn_hk_toggle)

        self.btn_tools = make_button("Инструменты", "Стыковка, линейка, калибровка, пресеты, поправки осей")
        self.btn_tools.setObjectName("btnTools")
        self.btn_tools.setMinimumHeight(24)
        self.btn_tools.clicked.connect(lambda: self.open_tools(0))
        bar.addWidget(self.btn_tools, 1)

        self.btn_mini = self._small_button("▾", "Свернуть до полоски")
        self.btn_mini.clicked.connect(self._toggle_mini_mode)
        bar.addWidget(self.btn_mini)
        return bar

    def _build_calibration_banner(self) -> QWidget:
        self.calib_banner_frame = QWidget()
        row = QHBoxLayout(self.calib_banner_frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.lbl_calib_banner = make_label("", word_wrap=True)
        self.lbl_calib_banner.setObjectName("calibActiveBanner")
        row.addWidget(self.lbl_calib_banner, 1)

        self.btn_calib_timer3s = make_button("3 сек", "Зафиксировать точку под курсором через 3 секунды")
        self.btn_calib_timer3s.clicked.connect(lambda: self.calibration_flow.start_countdown(3))
        row.addWidget(self.btn_calib_timer3s)

        self.btn_calib_cancel = make_button("×", "Отменить калибровку")
        self.btn_calib_cancel.setMaximumWidth(26)
        self.btn_calib_cancel.clicked.connect(self.calibration_flow.cancel)
        row.addWidget(self.btn_calib_cancel)

        self.calib_banner_frame.setVisible(False)
        return self.calib_banner_frame

    def _build_main_actions(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(4)

        main_row = QHBoxLayout()
        main_row.setSpacing(4)
        self.btn_capture = make_button("", "Считать координаты выделенного объекта (Ctrl+A / Ctrl+C)")
        self.btn_capture.setObjectName("btnCapture")
        self.btn_capture.setMinimumHeight(32)
        self.btn_capture.clicked.connect(self.action_capture_from_game)
        main_row.addWidget(self.btn_capture, 1)

        self.btn_save_commit = make_button("", "Кликнуть мимо поля и нажать Enter — зафиксировать координаты")
        self.btn_save_commit.setObjectName("btnSaveCommit")
        self.btn_save_commit.setMinimumHeight(32)
        self.btn_save_commit.clicked.connect(self.action_commit_save_in_game)
        main_row.addWidget(self.btn_save_commit, 1)
        column.addLayout(main_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(4)
        self.btn_paste_all = self._small_button(
            "Вставить всё", "Принудительно ввести все 6 координат в выделенный объект"
        )
        self.btn_paste_all.clicked.connect(self.action_paste_all_to_game)
        sub_row.addWidget(self.btn_paste_all, 1)

        self.btn_undo = self._small_button("↶", "Отменить последний шаг (Alt+Z)")
        self.btn_undo.clicked.connect(self.action_undo)
        sub_row.addWidget(self.btn_undo)

        self.btn_redo = self._small_button("↷", "Повторить отменённый шаг")
        self.btn_redo.clicked.connect(self.action_redo)
        sub_row.addWidget(self.btn_redo)
        column.addLayout(sub_row)
        return column

    def _build_tools_dialog(self) -> None:
        self.tools = ToolsDialog(self.settings, self.controller.advance_reference_on_join, self)
        mv = self.tools.movement_tab
        mv.space_changed.connect(self._on_move_space_changed)
        mv.rotate_requested.connect(self.action_rotate_yaw)
        mv.angle_step_changed.connect(self._on_angle_step_changed)
        mv.set_anchor_requested.connect(self.action_set_anchor_from_current)
        mv.snap_anchor_requested.connect(self.action_snap_anchor)
        mv.preset_requested.connect(self.action_apply_preset)
        mv.invert_changed.connect(self._on_invert_changed)
        mv.test_move_requested.connect(self.action_test_move)
        mv.test_rotate_requested.connect(self.action_test_rotate)

        jt = self.tools.join_tab
        jt.prop_size_changed.connect(self._on_prop_size_changed)
        jt.saved_size_picked.connect(self._on_saved_size_picked)
        jt.save_size_requested.connect(self._save_current_prop_size)
        jt.reference_save_requested.connect(self.action_save_reference)
        jt.advance_reference_changed.connect(self._on_advance_reference_changed)
        jt.align_requested.connect(self.action_align_to_reference)
        jt.join_requested.connect(self.action_join_section)
        jt.edge_rotate_requested.connect(self.action_rotate_edge)
        jt.point_a_requested.connect(self.action_record_point_a)
        jt.point_b_requested.connect(self.action_record_point_b)
        jt.ruler_anchor_requested.connect(self.action_ruler_to_anchor)
        jt.ruler_mid_requested.connect(self.action_move_to_ruler_midpoint)
        jt.btn_to_step.clicked.connect(
            lambda: self.quick.set_step_value(jt.spin_prop_size.value())
        )

        ct = self.tools.calibration_tab
        ct.wizard_requested.connect(self.start_full_calibration)
        ct.single_requested.connect(self.start_single_calibration)
        ct.fast_capture_toggled.connect(self._on_fast_capture_toggled)
        ct.unfocus_toggled.connect(self._on_unfocus_toggled)
        ct.safe_verify_toggled.connect(self._on_safe_verify_toggled)
        ct.max_jump_changed.connect(self._on_max_jump_changed)

        self.tools.settings_requested.connect(self._open_settings_dialog)

    def open_tools(self, index: int = 0) -> None:
        self.tools.show_tab(index)

    # ------------------------------------------------------------------ состояние
    def _save_settings(self) -> None:
        self.config_store.save(self.settings)

    def _update_button_hotkey_titles(self) -> None:
        hk = self.settings.hotkeys
        self.btn_capture.setText(f"Захват  {hk.capture or '—'}")
        self.btn_save_commit.setText(f"Сохранить  {hk.save_commit or '—'}")
        self.btn_paste_all.setText(f"Вставить всё  {hk.paste_all or '—'}")
        self.calib_tab.set_hotkey_title(hk.calibrate_point)

    def _sync_ui_from_state(self) -> None:
        t = self.controller.current
        self.field_box.set_decimals(
            {
                f: (self.settings.rot_decimals if f in ROT_FIELDS else self.settings.pos_decimals)
                for f in FIELD_NAMES
            }
        )
        self.field_box.set_values({f: t.get_field(f) for f in FIELD_NAMES})

        use_anchor = self.settings.move_space == MoveSpace.ANCHOR_HORIZONTAL.value
        self.tools.movement_tab.update_state(t.rz, self.settings.anchor_rz, use_anchor)
        self.quick.set_heading(t.rz)
        self.quick.set_step_value(self.settings.step)

        self.btn_undo.setEnabled(self.controller.can_undo())
        self.btn_redo.setEnabled(self.controller.can_redo())

        self.tools.join_tab.set_reference_state(self.controller.reference_transform)

    def _refresh_calibration_labels(self) -> None:
        self.calib_tab.refresh_points(self.settings.calibration)

    def lbl_calib_banner_setText(self, text: str) -> None:
        self.lbl_calib_banner.setText(text)

    def _set_status(self, message: str, error: bool = False) -> None:
        self.lbl_status.setText(message)
        self.lbl_status.setToolTip(message)
        if error:
            logger.warning("Статус (ошибка): %s", message)
            self.lbl_status.setStyleSheet(
                "background-color: #3b1219; border: 1px solid #ef4444; color: #fecaca; "
                "border-radius: 4px; padding: 4px 6px;"
            )
        else:
            logger.info("Статус: %s", message)
            self.lbl_status.setStyleSheet("")

    # ------------------------------------------------------------------ окно и хоткеи
    def _toggle_always_on_top(self, checked: bool) -> None:
        self.settings.always_on_top = checked
        self._save_settings()
        pos = self.pos()
        self._setup_window_flags()
        self.move(pos)
        self.show()

    def _toggle_mini_mode(self) -> None:
        self._mini_mode = not self._mini_mode
        self.body_container.setVisible(not self._mini_mode)
        self.btn_mini.setText("▴" if self._mini_mode else "▾")
        self.adjustSize()

    def _toggle_hotkeys(self, checked: bool) -> None:
        self.settings.hotkeys_enabled = checked
        self._save_settings()
        self._restart_hotkeys()
        self._set_status("Горячие клавиши включены." if checked else "Горячие клавиши отключены.")

    def _restart_hotkeys(self) -> None:
        self.hotkey_service.stop()
        hk = self.settings.hotkeys
        if not self.settings.hotkeys_enabled:
            if self.calibration_flow.is_active and hk.calibrate_point:
                self.hotkey_service.start({"calibrate_point": hk.calibrate_point})
            return

        failed = self.hotkey_service.start(hk.to_dict())
        if failed:
            self._set_status(f"Хоткеи заняты другой программой: {', '.join(failed)}", error=True)

    def _open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply_to_settings()
            self.setWindowOpacity(self.settings.window_opacity)
            self._save_settings()
            self._update_button_hotkey_titles()
            self._sync_ui_from_state()
            self._restart_hotkeys()
            self._set_status("Настройки сохранены.")

    # ------------------------------------------------------------------ калибровка
    def start_full_calibration(self) -> None:
        self.calibration_flow.start_full()

    def start_single_calibration(self, target: str) -> None:
        self.calibration_flow.start_single(target)

    def _on_calibration_active_changed(self, active: bool) -> None:
        self.calib_banner_frame.setVisible(active)
        self._restart_hotkeys()

    def _on_calibration_point(self, target: str, x: int, y: int) -> None:
        self.settings.calibration.set_point(target, x, y)
        self._save_settings()
        self._refresh_calibration_labels()
        if self.calibration_flow.is_active:
            self._set_status(f"Записано «{CALIBRATION_LABELS[target]}»: {x}, {y}")

    def _on_calibration_finished(self) -> None:
        self._set_status("Калибровка завершена и сохранена.")

    def _on_calibration_cancelled(self) -> None:
        self._set_status("Калибровка отменена.")

    # ------------------------------------------------------------------ обработчики
    def _on_fast_capture_toggled(self, val: bool) -> None:
        self.settings.fast_capture_skip_tilt = val
        self._save_settings()

    def _on_unfocus_toggled(self, val: bool) -> None:
        self.settings.unfocus_after_paste = val
        self._save_settings()

    def _on_safe_verify_toggled(self, val: bool) -> None:
        self.settings.safe_write_verify = val
        self._save_settings()

    def _on_max_jump_changed(self, val: float) -> None:
        self.settings.max_jump = float(val)
        self._save_settings()

    def _on_invert_changed(self, name: str, value: bool) -> None:
        mapping = {
            "forward": "invert_forward",
            "right": "invert_right",
            "up": "invert_up",
            "rotate": "invert_rotate",
        }
        attr = mapping.get(name)
        if attr is None:
            return
        setattr(self.settings, attr, bool(value))
        self._save_settings()
        logger.info("Поправка направления '%s' = %s", name, value)
        self._set_status(
            f"Направление «{name}» инвертировано: {value}." if value else f"Направление «{name}» обычное."
        )

    def _on_move_space_changed(self, space: str) -> None:
        self.settings.move_space = space
        self._save_settings()
        self._sync_ui_from_state()

    def _on_step_changed(self, val: float) -> None:
        self.settings.step = float(val)
        self._save_settings()

    def _on_angle_step_changed(self, val: float) -> None:
        self.settings.angle_step = float(val)
        self._save_settings()

    def _on_prop_size_changed(self, val: float) -> None:
        self.settings.prop_size = float(val)
        self._save_settings()

    def _on_advance_reference_changed(self, val: bool) -> None:
        self.controller.advance_reference_on_join = bool(val)

    def _on_saved_size_picked(self, size: float) -> None:
        self.join_tab.spin_prop_size.setValue(size)
        self.quick.set_step_value(size)

    def _save_current_prop_size(self) -> None:
        sz = self.join_tab.spin_prop_size.value()
        name, ok = QInputDialog.getText(
            self, "Сохранить размер пропа", f"Название для размера {format_number(sz, 4)} м:"
        )
        if ok and name.strip():
            self.settings.saved_prop_sizes.append({"name": name.strip(), "size": sz})
            self._save_settings()
            self.join_tab.reload_saved_sizes()
            self._set_status(f"Размер «{name.strip()}» сохранён.")

    def _on_manual_field_edited(self, field_name: str) -> None:
        new_val = self.field_box.value_of(field_name)
        old_val = self.controller.current.get_field(field_name)
        if abs(new_val - old_val) < 1e-7:
            return
        dirty = self.controller.set_single_field(field_name, new_val)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, action_label=f"Ввод {field_name.upper()}")

    # ------------------------------------------------------------------ макросы
    def _on_macro_busy(self, busy: bool) -> None:
        for btn in (self.btn_capture, self.btn_save_commit, self.btn_paste_all):
            btn.setEnabled(not busy)

    def _on_macro_finished(self, msg: str, payload: object) -> None:
        if isinstance(payload, Transform):
            self.controller.set_captured_transform(payload)
            self._sync_ui_from_state()
        elif isinstance(payload, list):
            self.controller.mark_synced(payload)
        self._pending_rollback = None
        self._set_status(msg, error=False)

    def _on_macro_failed(self, err_msg: str) -> None:
        self._set_status(err_msg, error=True)
        pending = self._pending_rollback
        self._pending_rollback = None
        if pending is None:
            return

        baseline, fields = pending
        if not fields:
            return

        logger.warning("Вставка не подтверждена — возвращаю прежние координаты в поля игры")
        automator = self.automator
        cal = self.settings.calibration
        timings = self.settings.timings
        pos_dec = self.settings.pos_decimals
        rot_dec = self.settings.rot_decimals

        def _job() -> tuple[str, object]:
            automator.write_fields(
                transform=baseline,
                fields=fields,
                calibration=cal,
                timings=timings,
                pos_decimals=pos_dec,
                rot_decimals=rot_dec,
                verify=False,
            )
            return "Возвращены прежние координаты (ввод отменён).", []

        self.macro_runner.run(_job, label="Откат")

    def _maybe_push_to_game(self, dirty_fields: list[str], action_label: str) -> None:
        if not self.settings.auto_apply_to_game:
            self._set_status(f"{action_label}: пересчитано локально (авто-ввод выключен).")
            return

        if not dirty_fields and not self.settings.auto_save_enter:
            self._set_status(f"{action_label}: координаты не изменились.")
            return

        snap = self.controller.current
        baseline = self.controller.panel_synced
        if baseline is not None and dirty_fields:
            jump = math.dist(
                (baseline.x, baseline.y, baseline.z), (snap.x, snap.y, snap.z)
            )
            if jump > self.settings.max_jump:
                message = (
                    f"{action_label}: скачок {jump:.1f} м больше лимита {self.settings.max_jump:.0f} м — "
                    "ввод заблокирован. Нажмите «Захват», чтобы синхронизировать координаты."
                )
                logger.error("Заблокирован ввод: скачок %.2f м (лимит %.2f м)", jump, self.settings.max_jump)
                self._set_status(message, error=True)
                return

        self._pending_rollback = (baseline, list(dirty_fields)) if baseline is not None else None

        automator = self.automator
        cal = self.settings.calibration
        timings = self.settings.timings
        pos_dec = self.settings.pos_decimals
        rot_dec = self.settings.rot_decimals
        save_enter = self.settings.auto_save_enter
        unfocus = self.settings.unfocus_after_paste
        verify = self.settings.safe_write_verify

        def _job() -> tuple[str, object]:
            written = automator.write_fields(
                transform=snap,
                fields=dirty_fields,
                calibration=cal,
                timings=timings,
                pos_decimals=pos_dec,
                rot_decimals=rot_dec,
                unfocus_after=unfocus,
                save_with_enter=save_enter,
                verify=verify,
            )
            fields_str = ", ".join(f.upper() for f in written) if written else "без изм."
            suffix = " + Сохранено" if save_enter else ""
            return f"{action_label} → [{fields_str}]{suffix}", written

        self.macro_runner.run(_job, label=action_label)

    # ------------------------------------------------------------------ команды
    def _on_hotkey_action(self, action_id: str) -> None:
        if action_id == "calibrate_point":
            self.calibration_flow.capture_now()
            return

        dispatch: dict[str, Callable[[], None]] = {
            "capture": self.action_capture_from_game,
            "save_commit": self.action_commit_save_in_game,
            "paste_all": self.action_paste_all_to_game,
            "move_forward": lambda: self.action_move(0.0, 1.0, 0.0),
            "move_back": lambda: self.action_move(0.0, -1.0, 0.0),
            "move_left": lambda: self.action_move(-1.0, 0.0, 0.0),
            "move_right": lambda: self.action_move(1.0, 0.0, 0.0),
            "move_up": lambda: self.action_move(0.0, 0.0, 1.0),
            "move_down": lambda: self.action_move(0.0, 0.0, -1.0),
            "rot_left_90": lambda: self.action_rotate_yaw(90.0),
            "rot_right_90": lambda: self.action_rotate_yaw(-90.0),
            "undo": self.action_undo,
        }
        fn = dispatch.get(action_id)
        if fn is not None:
            fn()

    def action_capture_from_game(self) -> None:
        cal = self.settings.calibration
        timings = self.settings.timings
        skip_tilt = self.settings.fast_capture_skip_tilt
        base_t = self.controller.current
        automator = self.automator

        def _job() -> tuple[str, object]:
            captured = automator.read_transform(
                calibration=cal, timings=timings, skip_tilt=skip_tilt, base_transform=base_t
            )
            return (
                f"Захвачено: X={captured.x:.3f} Y={captured.y:.3f} Z={captured.z:.3f} RZ={captured.rz:+.2f}°",
                captured,
            )

        self.macro_runner.run(_job, label="Захват")

    def action_paste_all_to_game(self) -> None:
        snap = self.controller.current
        cal = self.settings.calibration
        timings = self.settings.timings
        pos_dec = self.settings.pos_decimals
        rot_dec = self.settings.rot_decimals
        save_enter = self.settings.auto_save_enter
        unfocus = self.settings.unfocus_after_paste
        verify = self.settings.safe_write_verify
        automator = self.automator
        self._pending_rollback = (
            (self.controller.panel_synced, list(FIELD_NAMES))
            if self.controller.panel_synced is not None
            else None
        )

        def _job() -> tuple[str, object]:
            written = automator.write_fields(
                transform=snap,
                fields=FIELD_NAMES,
                calibration=cal,
                timings=timings,
                pos_decimals=pos_dec,
                rot_decimals=rot_dec,
                unfocus_after=unfocus,
                save_with_enter=save_enter,
                verify=verify,
            )
            suffix = " + Сохранено" if save_enter else ""
            return f"Вставлены все координаты{suffix}.", written

        self.macro_runner.run(_job, label="Вставить всё")

    def action_commit_save_in_game(self) -> None:
        dirty = self.controller.compute_dirty_fields()
        snap = self.controller.current
        cal = self.settings.calibration
        timings = self.settings.timings
        pos_dec = self.settings.pos_decimals
        rot_dec = self.settings.rot_decimals
        auto_apply = self.settings.auto_apply_to_game
        verify = self.settings.safe_write_verify
        automator = self.automator

        def _job() -> tuple[str, object]:
            if dirty and not auto_apply:
                written = automator.write_fields(
                    transform=snap,
                    fields=dirty,
                    calibration=cal,
                    timings=timings,
                    pos_decimals=pos_dec,
                    rot_decimals=rot_dec,
                    save_with_enter=True,
                    verify=verify,
                )
                return "Изменения введены и сохранены.", written
            automator.commit_save_only(calibration=cal, timings=timings)
            return "Сохранено в игре (Клик мимо + Enter).", []

        self.macro_runner.run(_job, label="Сохранение")

    def action_move(self, right: float = 0.0, forward: float = 0.0, up: float = 0.0) -> None:
        dirty = self.controller.move_step(right_sign=right, forward_sign=forward, up_sign=up)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, f"Сдвиг {format_number(self.settings.step, 3)} м")

    def action_test_move(self) -> None:
        dirty = self.controller.move_step(forward_sign=1.0, custom_distance=0.05)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, "Тест: 5 см вперёд")

    def action_test_rotate(self) -> None:
        dirty = self.controller.rotate_by(15.0)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, "Тест: поворот 15°")

    def action_rotate_yaw(self, delta_deg: float) -> None:
        dirty = self.controller.rotate_by(delta_deg)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, f"Поворот {delta_deg:+.0f}°")

    def action_set_anchor_from_current(self) -> None:
        ang = self.controller.set_anchor_from_current()
        self._save_settings()
        self._sync_ui_from_state()
        self._set_status(f"Базовый угол комнаты: {ang:+.2f}°")

    def action_snap_anchor(self, offset_deg: float) -> None:
        dirty = self.controller.snap_to_room_anchor(offset_deg)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, f"По якорю {offset_deg:+.0f}°")

    def action_apply_preset(self, preset_key: str) -> None:
        dirty = self.controller.apply_preset(preset_key)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, "Пресет положения")

    def action_save_reference(self) -> None:
        ref = self.controller.save_reference_from_current()
        self._sync_ui_from_state()
        self._set_status(
            f"Эталон сохранён: X={ref.x:.2f} Y={ref.y:.2f} Z={ref.z:.2f} RZ={ref.rz:+.1f}°"
        )

    def action_align_to_reference(self) -> None:
        try:
            dirty = self.controller.align_to_reference()
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, "Подтяжка к эталону")

    def action_join_section(self, direction: str, turn_deg: float) -> None:
        dirty = self.controller.join_section_from_reference(direction=direction, turn_deg=turn_deg)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, f"Стыковка ({direction}, {turn_deg:+.0f}°)")

    def action_rotate_edge(self, delta_deg: float, edge: str) -> None:
        dirty = self.controller.rotate_around_prop_edge(delta_deg, edge)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, f"Поворот за край ({edge})")

    def action_record_point_a(self) -> None:
        pt = self.controller.set_ruler_point_a()
        self.join_tab.show_measurement(self.controller.get_ruler_measurement())
        self._set_status(f"Точка A: ({pt.x:.3f}, {pt.y:.3f}, {pt.z:.3f})")

    def action_record_point_b(self) -> None:
        pt = self.controller.set_ruler_point_b()
        self.join_tab.show_measurement(self.controller.get_ruler_measurement())
        self._set_status(f"Точка B: ({pt.x:.3f}, {pt.y:.3f}, {pt.z:.3f})")

    def action_ruler_to_anchor(self) -> None:
        meas = self.controller.get_ruler_measurement()
        if meas is None:
            self._set_status("Сначала запишите точки A и B.", error=True)
            return
        self.settings.anchor_rz = meas.rz_along_x
        self._save_settings()
        self._sync_ui_from_state()
        self._set_status(f"Угол A→B ({meas.rz_along_x:+.3f}°) — якорь комнаты.")

    def action_move_to_ruler_midpoint(self) -> None:
        meas = self.controller.get_ruler_measurement()
        if meas is None:
            self._set_status("Сначала запишите точки A и B.", error=True)
            return
        mid = Transform(
            x=meas.midpoint.x,
            y=meas.midpoint.y,
            z=meas.midpoint.z,
            rx=self.controller.current.rx,
            ry=self.controller.current.ry,
            rz=meas.rz_along_x,
        )
        dirty = self.controller.update_transform(mid)
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, "Центр A–B")

    def action_undo(self) -> None:
        dirty = self.controller.undo()
        if dirty is None:
            self._set_status("История отмены пуста.")
            return
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, "Отмена")

    def action_redo(self) -> None:
        dirty = self.controller.redo()
        if dirty is None:
            self._set_status("Нечего повторять.")
            return
        self._sync_ui_from_state()
        self._maybe_push_to_game(dirty, "Повтор")

    # ------------------------------------------------------------------ завершение
    def closeEvent(self, event) -> None:  # noqa: N802
        logger.info("Закрытие главного окна")
        self.calibration_flow.shutdown()
        self.hotkey_service.stop()
        self._save_settings()
        self.tools.close()
        super().closeEvent(event)
