"""Главное окно оверлея: вкладки, сценарии, горячие клавиши."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from map_overlay import __version__, diagnostics
from map_overlay.application.hotkeys import HotkeyRouter
from map_overlay.application.session import MappingSession, StepResult
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.actions import Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.formatting import format_delta, format_value
from map_overlay.domain.keynames import COMMON_GAME_KEYS, VK_ESCAPE, key_name
from map_overlay.domain.movement import COORD_DECIMALS
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.errors import ConfigError, ValidationError
from map_overlay.ui.tabs.calibration_tab import CalibrationTab
from map_overlay.ui.tabs.movement_tab import MovementTab, pose_text
from map_overlay.ui.tabs.settings_tab import SettingsTab
from map_overlay.ui.tasks import TaskRunner
from map_overlay.ui.widgets import button, label

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 780
WINDOW_HEIGHT = 840
STATUS_INFO = "info"
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ERROR = "error"
STATUS_ROLES: dict[str, str] = {
    STATUS_INFO: "muted",
    STATUS_OK: "ok",
    STATUS_WARN: "warn",
    STATUS_ERROR: "error",
}
HOOK_CHECK_MS = 800
HEARTBEAT_MS = 250
BUSY_TICK_MS = 500
STUCK_HINT_S = 5.0
HOLD_REPEAT_MS = 150
"""Как часто повторять шаг, пока направление на Numpad зажато."""
LEARN_TIMEOUT_MS = 10_000


class MainWindow(QMainWindow):
    """Собирает вкладки и управляет сценариями панели."""

    def __init__(self, context: AppContext, *, synchronous_tasks: bool = False) -> None:
        super().__init__()
        self._context = context
        self._session: MappingSession | None = None
        self._pose: Pose | None = None
        self._learning: Action | None = None
        self._runner = TaskRunner(synchronous=synchronous_tasks, parent=self)
        self._router = HotkeyRouter(context.settings.hotkeys)
        self._busy_text = ""
        self._held: tuple[Action, int] | None = None
        self._learn_timer = QTimer(self)
        self._learn_timer.setSingleShot(True)
        self._learn_timer.timeout.connect(self._learning_expired)
        self._build()
        self._refresh_header()
        self._hotkeys = context.hotkeys
        self._hotkeys.start_listening(self._on_hotkey)
        self._apply_hotkeys(context.settings.hotkeys)
        QTimer.singleShot(HOOK_CHECK_MS, self.check_hotkey_state)
        if context.settings_error:
            self._set_status(f"Настройки не загружены: {context.settings_error}", STATUS_ERROR)
        else:
            self._set_status("Выберите поля, нажмите «Считать» и двигайте предмет стрелками.")
            self._check_num_lock()

    def _build(self) -> None:
        self.setWindowTitle(f"Map Overlay Redux {__version__}")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        # Окно не отбирает фокус у игры при запуске: клавиатура остаётся у игры.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        central = QWidget(self)
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 10)
        layout.setSpacing(10)
        layout.addWidget(self._build_header(central))

        settings = self._context.settings
        self._tabs = QTabWidget(central)
        self.movement = MovementTab(default_step=settings.default_step)
        self.calibration = CalibrationTab(
            cursor=self._context.cursor,
            points=settings.calibration,
            empty_point=settings.empty_point,
        )
        self.settings_tab = SettingsTab(settings=settings, config_path=self._context.config_path)
        self._tabs.addTab(self._scroll(self.movement), "Движение")
        self._tabs.addTab(self._scroll(self.calibration), "Калибровка")
        self._tabs.addTab(self._scroll(self.settings_tab), "Настройки")
        layout.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

        self._status = QLabel("", self)
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        self.statusBar().addWidget(self._status, 1)
        self._abort_button = button(
            "Прервать",
            widget_role="small",
            tooltip="Бросить текущее действие, если панель не отвечает",
        )
        self._abort_button.setEnabled(False)
        self._abort_button.clicked.connect(self._abort_action)
        self.statusBar().addPermanentWidget(self._abort_button)

        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(BUSY_TICK_MS)
        self._busy_timer.timeout.connect(self._busy_tick)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(diagnostics.beat)
        self._heartbeat.start()
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(HOLD_REPEAT_MS)
        self._hold_timer.timeout.connect(self._hold_tick)

        self.movement.capture_requested.connect(self._capture)
        self.movement.confirm_requested.connect(self._confirm)
        self.movement.move_requested.connect(self._move)
        self.calibration.points_changed.connect(self._calibration_changed)
        self.calibration.empty_point_changed.connect(self._empty_point_changed)
        self.calibration.status_message.connect(self._set_calibration_status)
        self.settings_tab.settings_saved.connect(self._settings_saved)
        self.settings_tab.status_message.connect(self._set_error_status)
        self.settings_tab.hotkey_change_requested.connect(self._start_learning)
        self.settings_tab.hotkey_clear_requested.connect(self._clear_hotkey)
        self.settings_tab.hotkeys_enabled_changed.connect(self._set_hotkeys_enabled)

    def _scroll(self, inner: QWidget) -> QScrollArea:
        """Обернуть вкладку в прокрутку: окно не растёт выше экрана."""
        area = QScrollArea(self)
        area.setWidget(inner)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        return area

    def _build_header(self, parent: QWidget) -> QWidget:
        header = QWidget(parent)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Map Overlay Redux", widget_role="appTitle"))
        layout.addWidget(label(f"v{__version__}", widget_role="muted"))
        layout.addStretch(1)
        self._calibration_label = label("", widget_role="muted")
        self._calibration_label.setWordWrap(False)
        layout.addWidget(self._calibration_label)
        return header

    def _refresh_header(self) -> None:
        settings = self._context.settings
        points = len(settings.calibration)
        empty = "есть" if settings.has_confirmation_point() else "нет"
        self._calibration_label.setText(f"Калибровка {points}/6 · F: {empty}")

    def tab_titles(self) -> list[str]:
        """Названия вкладок по порядку."""
        return [self._tabs.tabText(index) for index in range(self._tabs.count())]

    def status_text(self) -> str:
        """Текст строки состояния (для тестов и журнала)."""
        return self._status.text()

    def _set_status(self, text: str, kind: str = STATUS_INFO) -> None:
        self._status.setText(text)
        self._status.setProperty("role", STATUS_ROLES.get(kind, STATUS_ROLES[STATUS_INFO]))
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _set_calibration_status(self, text: str) -> None:
        self._set_status(text, STATUS_INFO)

    def _set_error_status(self, text: str) -> None:
        self._set_status(text, STATUS_ERROR)

    def _set_busy(self, busy: bool) -> None:
        self.movement.set_busy(busy)
        self._abort_button.setEnabled(busy)
        if busy:
            self._busy_timer.start(BUSY_TICK_MS)
        else:
            self._busy_timer.stop()

    def _begin_busy(self, text: str) -> None:
        """Показать, что идёт обмен с панелью, и засечь время."""
        self._busy_text = text
        self._set_busy(True)
        self._set_status(text)

    def _busy_tick(self) -> None:
        """Обновлять счётчик времени, чтобы «занято» не выглядело как «зависло»."""
        if not self._runner.is_busy():
            self._busy_timer.stop()
            return
        seconds = self._runner.busy_seconds()
        if seconds >= STUCK_HINT_S:
            self._set_status(
                f"{self._busy_text} ({seconds:.0f} с) — панель не отвечает? Нажмите «Прервать».",
                STATUS_WARN,
            )
            return
        self._set_status(f"{self._busy_text} ({seconds:.0f} с)")

    def _abort_action(self) -> None:
        """Бросить зависшее действие, не закрывая окно."""
        self._stop_hold()
        if not self._runner.abandon():
            return
        self._set_busy(False)
        self._set_status(
            "Действие прервано вручную, удержание остановлено. "
            "Если панель не отвечает, перезапустите оверлей.",
            STATUS_WARN,
        )

    def _ensure_session(self) -> MappingSession:
        if self._session is None:
            self._session = self._context.make_session()
        return self._session

    # --- действия ---------------------------------------------------------

    def _capture(self) -> None:
        self._stop_hold()
        if self._runner.is_busy():
            return
        session = self._ensure_session()
        self._begin_busy("Читаю поля панели…")
        self._runner.submit(
            session.capture,
            on_success=self._captured,
            on_error=self._failed,
            label="считать координаты",
        )

    def _confirm(self) -> None:
        self._stop_hold()
        if self._runner.is_busy():
            return
        session = self._ensure_session()
        self._begin_busy("Подтверждаю положение: клик в пустое место и F…")
        self._runner.submit(
            session.confirm,
            on_success=self._confirmed,
            on_error=self._failed,
            label="сохранить F",
        )

    def _move(self, direction: object, step: float, *, tilt: bool = False) -> bool:
        """Сделать шаг; ``tilt`` — по наклону ``RX`` (клавиша Alt).

        Returns:
            ``True``, если задача поставлена: ``False`` — шаг невозможен.
        """
        if self._runner.is_busy():
            return False
        session = self._session
        if session is None or session.pose is None or self._pose is None:
            self._set_status(
                "Сначала нажмите «Считать»: без координат шаг не посчитать", STATUS_WARN
            )
            return False
        selected = cast(Direction, direction)
        suffix = ""
        if tilt:
            suffix = f" (по наклону RX {format_value(self._pose.rx, COORD_DECIMALS)}°)"
        self._begin_busy(f"Шаг {selected.label} на {step:g} м{suffix}…")
        self._runner.submit(
            lambda: session.step(selected, step, tilt=tilt),
            on_success=self._moved,
            on_error=self._failed,
            label=f"шаг {selected.label.lower()} на {step:g} м{suffix}",
        )
        return True

    def _captured(self, result: object) -> None:
        self._set_busy(False)
        pose = cast(Pose, result)
        self._pose = pose
        self.movement.set_pose(pose)
        self.movement.set_warning(self._tilt_warning(pose))
        self._set_status(f"Считано: {pose_text(pose)}", STATUS_OK)

    def _moved(self, result: object) -> None:
        self._set_busy(False)
        step_result = cast(StepResult, result)
        self._pose = step_result.pose
        self.movement.set_pose(step_result.pose)
        self.movement.set_warning(self._tilt_warning(step_result.pose))
        written = ", ".join(field.label for field in step_result.written) or "ничего"
        deltas = f"ΔX {format_delta(step_result.delta_x)} · ΔY {format_delta(step_result.delta_y)}"
        slope = ""
        if step_result.tilted:
            deltas = f"{deltas} · ΔZ {format_delta(step_result.delta_z)}"
            slope = f" · по наклону RX {format_value(step_result.pose.rx, COORD_DECIMALS)}°"
        self._set_status(
            f"Шаг: {deltas} → {pose_text(step_result.pose)} · записано: {written}{slope}",
            STATUS_OK,
        )

    def _confirmed(self, _result: object) -> None:
        self._set_busy(False)
        self._set_status("Положение подтверждено клавишей F", STATUS_OK)

    def _failed(self, message: str) -> None:
        logger.warning("Действие не выполнено: %s", message)
        self._stop_hold()
        self._set_busy(False)
        self._set_status(message, STATUS_ERROR)

    def _tilt_warning(self, pose: Pose) -> str:
        if not pose.has_tilt:
            return ""
        parts: list[str] = []
        if abs(pose.rx) > 1e-9:
            parts.append(
                f"RX {format_value(pose.rx, COORD_DECIMALS)}°: Alt + направление ведёт по "
                "наклону (при RX > 0 «вперёд» поднимает), без Alt — по плоскости."
            )
        if abs(pose.ry) > 1e-9:
            parts.append(f"RY {format_value(pose.ry, COORD_DECIMALS)}° не учитывается.")
        return " ".join(parts)

    # --- горячие клавиши --------------------------------------------------

    def _on_hotkey(self, vk: int, is_down: bool) -> None:
        if not self.settings_tab.hotkeys_enabled():
            return
        if self._learning is not None:
            if is_down:
                self._finish_learning(vk)
            return
        action = self._router.handle(vk, is_down)
        if action is not None:
            self._dispatch(action, vk)
        elif not is_down:
            self._release_key(vk)

    def _dispatch(self, action: Action, vk: int) -> None:
        if action is Action.CAPTURE:
            self._capture()
            return
        if action is Action.CONFIRM:
            self._confirm()
            return
        if action.direction is not None:
            self._start_hold(action, vk)

    # --- удержание направления -------------------------------------------

    def _start_hold(self, action: Action, vk: int) -> None:
        """Начать удержание: первый шаг сразу, дальше — по таймеру."""
        self._stop_hold()
        self._held = (action, vk)
        self._hold_timer.start(HOLD_REPEAT_MS)
        self._hold_tick()

    def _hold_tick(self) -> None:
        """Повторить шаг, пока клавиша зажата.

        Пропускает такт, если панель ещё занята предыдущим шагом: очередь шагов
        не копится, иначе оверлей «уезжал» бы после отпускания клавиши.
        """
        held = self._held
        if held is None:
            self._hold_timer.stop()
            return
        action, vk = held
        if not self.settings_tab.hotkeys_enabled() or not self._hotkeys.key_down(vk):
            self._stop_hold()
            return
        if self._runner.is_busy():
            return
        if not self._step_once(action, tilt=self._hotkeys.alt_down()):
            self._stop_hold()

    def _step_once(self, action: Action, *, tilt: bool) -> bool:
        direction = action.direction
        if direction is None:
            return False
        try:
            step = self.movement.current_step()
        except ValidationError as exc:
            self._set_status(str(exc), STATUS_WARN)
            return False
        return self._move(direction, step, tilt=tilt)

    def _release_key(self, vk: int) -> None:
        """Отпускание клавиши прекращает удержание."""
        if self._held is not None and self._held[1] == vk:
            self._stop_hold()

    def _stop_hold(self) -> None:
        self._hold_timer.stop()
        self._held = None

    def _start_learning(self, action: object) -> None:
        self._stop_hold()
        if not self.settings_tab.hotkeys_enabled():
            self._set_status("Перехват клавиш выключен — назначить клавишу нельзя.", STATUS_WARN)
            return
        selected = cast(Action, action)
        self._learning = selected
        self._hotkeys.configure(bound_keys=self._router.bound_keys, learning=True)
        self._learn_timer.start(LEARN_TIMEOUT_MS)
        self._set_status(f"Нажмите клавишу для «{selected.label}» (Esc — отмена)")

    def _cancel_learning(self, reason: str) -> None:
        """Отменить запись привязки: клавиатура возвращается игре."""
        if self._learning is None:
            return
        self._learning = None
        self._learn_timer.stop()
        self._hotkeys.configure(bound_keys=self._router.bound_keys, learning=False)
        self._set_status(f"Назначение клавиши отменено: {reason}", STATUS_WARN)

    def _learning_expired(self) -> None:
        self._cancel_learning("время вышло")

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - имя из Qt
        """Потеря фокуса отменяет запись привязки: иначе окно «съест» клавиатуру."""
        super().changeEvent(event)
        activation = event.type() == QEvent.Type.ActivationChange
        if activation and not self.isActiveWindow():
            self._cancel_learning("окно потеряло фокус")

    def _set_hotkeys_enabled(self, enabled: bool) -> None:
        """Включить или приостановить перехват клавиш без перезапуска."""
        self._stop_hold()
        self._hotkeys.set_enabled(enabled)
        if enabled:
            self._set_status("Перехват клавиш включён: Numpad снова забран у игры.")
            self._check_num_lock()
        else:
            self._cancel_learning("перехват выключен")
            self._set_status(
                "Перехват выключен: игра получает все клавиши, кнопки работают мышью.",
                STATUS_WARN,
            )

    def _finish_learning(self, vk: int) -> None:
        action = self._learning
        self._learning = None
        self._learn_timer.stop()
        self._hotkeys.configure(bound_keys=self._router.bound_keys, learning=False)
        if action is None:
            return
        if vk == VK_ESCAPE:
            self._set_status("Назначение клавиши отменено")
            return
        try:
            settings = self._context.settings.with_hotkey(action, vk)
            self._context.save_settings(settings)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self._apply_hotkeys(settings.hotkeys)
        self._set_status(f"Клавиша {key_name(vk)} назначена на «{action.label}»", STATUS_OK)
        if vk in COMMON_GAME_KEYS:
            self._set_status(
                f"Клавиша {key_name(vk)} обычно занята в игре: теперь она достанется "
                f"оверлею, а не игре.",
                STATUS_WARN,
            )

    def _clear_hotkey(self, action: object) -> None:
        selected = cast(Action, action)
        try:
            settings = self._context.settings.with_hotkey(selected, None)
            self._context.save_settings(settings)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self._apply_hotkeys(settings.hotkeys)
        self._set_status(f"Клавиша для «{selected.label}» снята")

    def _apply_hotkeys(self, hotkeys: Mapping[Action, int | None]) -> None:
        self._router.bind(hotkeys)
        self._hotkeys.configure(
            bound_keys=self._router.bound_keys, learning=self._learning is not None
        )
        self.settings_tab.set_hotkeys(hotkeys)

    def _check_num_lock(self) -> None:
        state = self._hotkeys.num_lock_enabled()
        if state is False:
            warning = (
                "NumLock выключен: цифровой блок работает как навигация, "
                "горячие клавиши не сработают."
            )
            self.settings_tab.set_num_lock_warning(warning)
            self._set_status(warning, STATUS_WARN)
        else:
            self.settings_tab.set_num_lock_warning("")

    def check_hotkey_state(self) -> None:
        """Сообщить, если хук клавиатуры не установился."""
        if not self._hotkeys.is_available():
            self._set_status(
                "Горячие клавиши недоступны: хук клавиатуры не установлен (см. журнал). "
                "Кнопки в окне работают как обычно.",
                STATUS_ERROR,
            )

    # --- настройки и калибровка -------------------------------------------

    def _reset_session(self) -> None:
        self._session = None
        self._pose = None
        self.movement.set_pose(None)
        self.movement.set_warning("")

    def _calibration_changed(self, points: object) -> None:
        calibration = cast("Mapping[Field, Point]", points)
        try:
            self._context.save_settings(self._context.settings.with_calibration(calibration))
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self._reset_session()
        self._refresh_header()
        self.settings_tab.set_base_settings(self._context.settings)
        missing = self._context.settings.missing_points()
        if missing:
            titles = ", ".join(field.label for field in missing)
            self._set_status(f"Калибровка сохранена. Не хватает полей: {titles}", STATUS_WARN)
        else:
            self._set_status("Калибровка сохранена. Нажмите «Считать».")

    def _empty_point_changed(self, point: object) -> None:
        selected = cast("Point | None", point)
        try:
            self._context.save_settings(self._context.settings.with_empty_point(selected))
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self._refresh_header()
        self.settings_tab.set_base_settings(self._context.settings)
        if selected is None:
            self._set_status("Точка пустого места снята: «Сохранить F» недоступно", STATUS_WARN)
        else:
            self._set_status("Точка пустого места сохранена: «Сохранить F» готово.", STATUS_OK)

    def _settings_saved(self, settings: object) -> None:
        new_settings = cast(Settings, settings)
        try:
            self._context.save_settings(new_settings)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self._reset_session()
        self.movement.set_default_step(new_settings.default_step)
        self.calibration.set_points(new_settings.calibration)
        self.calibration.set_empty_point(new_settings.empty_point)
        self.settings_tab.set_base_settings(new_settings)
        self._apply_hotkeys(new_settings.hotkeys)
        self._refresh_header()
        self._set_status("Настройки сохранены. Нажмите «Считать» заново.", STATUS_OK)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - имя из Qt
        """Снять хук и дождаться фоновой задачи, чтобы не оставить поток висеть."""
        self._heartbeat.stop()
        self._hold_timer.stop()
        self._held = None
        self._hotkeys.stop_listening()
        self._runner.shutdown()
        super().closeEvent(event)
