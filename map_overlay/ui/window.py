"""Главное окно оверлея: сборка вкладок и связи между сценариями.

Окно — только каркас: оно собирает вкладки, строку состояния и таймеры, а сценарии
разложены по частям, каждая из которых живёт в своём модуле:

* ``window_layout`` — размеры по содержимому и мини-версия;
* ``window_actions`` — занятость, дедлайн обмена, «Прервать»;
* ``window_movement`` — «Считать», шаги, вставка, удержание, история;
* ``window_hotkeys`` — перехват клавиш, обучение, маршрутизация команд.

Состояние у частей общее — его объявляет ``window_base.WindowBase`` (см. там же
объяснение, почему это миксины, а не отдельные контроллеры).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from map_overlay import __version__, diagnostics
from map_overlay.application.history import Change, History
from map_overlay.application.hotkeys import HotkeyRouter
from map_overlay.application.metrics import METRICS
from map_overlay.application.session import MappingSession
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.actions import Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.errors import ConfigError
from map_overlay.paths import metrics_path
from map_overlay.trace import note
from map_overlay.ui.appicon import icon as app_icon
from map_overlay.ui.tabs.calibration_tab import CalibrationTab
from map_overlay.ui.tabs.movement_tab import MovementTab
from map_overlay.ui.tabs.settings_tab import SettingsTab
from map_overlay.ui.tabs.sizes_tab import SizesTab
from map_overlay.ui.tasks import TaskRunner
from map_overlay.ui.widgets import ROW_SPACING, button, label
from map_overlay.ui.window_actions import WindowActionsMixin
from map_overlay.ui.window_base import (
    BUSY_TICK_MS,
    HEARTBEAT_MS,
    HOOK_CHECK_MS,
    NUM_LOCK_CHECK_MS,
    STATE_LOG_MS,
    STATUS_ERROR,
    STATUS_INFO,
    STATUS_OK,
    STATUS_ROLES,
    STATUS_WARN,
)
from map_overlay.ui.window_hotkeys import WindowHotkeysMixin
from map_overlay.ui.window_layout import (
    MINI_HEIGHT as MINI_HEIGHT,
)
from map_overlay.ui.window_layout import (
    MINI_WIDTH as MINI_WIDTH,
)
from map_overlay.ui.window_layout import (
    WINDOW_HEIGHT as WINDOW_HEIGHT,
)
from map_overlay.ui.window_layout import (
    WINDOW_WIDTH as WINDOW_WIDTH,
)
from map_overlay.ui.window_layout import (
    WindowLayoutMixin,
)
from map_overlay.ui.window_movement import WindowMovementMixin

logger = logging.getLogger(__name__)


class MainWindow(
    WindowLayoutMixin,
    WindowActionsMixin,
    WindowMovementMixin,
    WindowHotkeysMixin,
):
    """Собирает вкладки и связывает их со сценариями панели."""

    def __init__(self, context: AppContext, *, synchronous_tasks: bool = False) -> None:
        super().__init__()
        self._context = context
        self._session: MappingSession | None = None
        self._pose: Pose | None = None
        self._learning: Action | None = None
        # История шагов: Ctrl+Z возвращает предмет на место до шага (ADR-0041).
        self._history = History()
        self._pending_kind: str | None = None
        self._pending_change: Change | None = None
        self._last_request: tuple[Direction, float, bool, bool] | None = None
        self._runner = TaskRunner(synchronous=synchronous_tasks, parent=self)
        self._router = HotkeyRouter(context.settings.hotkeys)
        self._busy_text = ""
        self._held: tuple[Action, int] | None = None
        self._refresh_on_step = False
        self._tilt_mode = False
        self._straight = context.settings.straight_cardinal
        self._always_read = context.settings.always_read_pose
        self._num_lock_state: bool | None = None
        self._learn_timer = QTimer(self)
        self._learn_timer.setSingleShot(True)
        self._learn_timer.timeout.connect(self._learning_expired)
        self._mini = False
        self._normal_size: tuple[int, int] | None = None
        self._normal_tab = 0
        self._build()
        self.movement.set_straight(self._straight)
        self.movement.set_always_read(self._always_read)
        self._refresh_header()
        self._hotkeys = context.hotkeys
        self._hotkeys.start_listening(self._on_hotkey)
        self._apply_hotkeys(context.settings.hotkeys)
        QTimer.singleShot(HOOK_CHECK_MS, self.check_hotkey_state)
        if context.settings_error:
            self._set_status(f"Настройки не загружены: {context.settings_error}", STATUS_ERROR)
        elif context.sizes_error:
            self._set_status(f"Размеры не загружены: {context.sizes_error}", STATUS_ERROR)
        else:
            self._set_status("Выберите поля, нажмите «Считать» и двигайте предмет стрелками.")
            self._check_num_lock()

    def _build(self) -> None:
        self.setWindowTitle(f"Mapper's Overlay Redux {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        # Окно не отбирает фокус у игры при запуске: клавиатура остаётся у игры.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._build_layout()
        self._build_status_bar()
        self._build_timers()
        self._connect_signals()

    def _build_layout(self) -> None:
        """Заголовок, три вкладки в прокрутке и центральный виджет."""
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
            settings=settings,
        )
        self.sizes = SizesTab(
            library=self._context.sizes,
            path=self._context.sizes_path,
        )
        self.settings_tab = SettingsTab(settings=settings, config_path=self._context.config_path)
        self.movement.set_sizes(self._context.sizes)
        self._tabs.addTab(self._scroll(self.movement), "Навигация")
        self._tabs.addTab(self._scroll(self.sizes), "Размеры")
        self._tabs.addTab(self._scroll(self.calibration), "Калибровка")
        self._tabs.addTab(self._scroll(self.settings_tab), "Настройки")
        layout.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

    def _build_status_bar(self) -> None:
        """Строка состояния с текстом и кнопкой «Прервать»."""
        self._status = QLabel("", self)
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        self.statusBar().addWidget(self._status, 1)
        # «Прервать» — кнопка с красной обводкой: заметная в нужный момент, но не
        # похожая на обычную кнопку «нажми меня».
        self._abort_button = button(
            "Прервать",
            widget_role="abort",
            tooltip="Бросить текущее действие, если панель не отвечает",
            accessible="Прервать действие",
        )
        self._abort_button.setEnabled(False)
        self._abort_button.clicked.connect(self._abort_action)
        self.statusBar().addPermanentWidget(self._abort_button)

    def _build_timers(self) -> None:
        """Таймеры: дедлайн действия, отсчёт занятости, сердцебиение, удержание, NumLock."""
        self._deadline_timer = QTimer(self)
        self._deadline_timer.setSingleShot(True)
        self._deadline_timer.timeout.connect(self._action_deadline)
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(BUSY_TICK_MS)
        self._busy_timer.timeout.connect(self._busy_tick)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(diagnostics.beat)
        self._heartbeat.start()
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._hold_tick)
        self._num_lock_timer = QTimer(self)
        self._num_lock_timer.setInterval(NUM_LOCK_CHECK_MS)
        self._num_lock_timer.timeout.connect(self._check_num_lock)
        self._num_lock_timer.start()
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(STATE_LOG_MS)
        self._state_timer.timeout.connect(self._log_state)
        self._state_timer.start()

    def _connect_signals(self) -> None:
        """Связи вкладок с окном."""
        self.movement.capture_requested.connect(self._capture)
        self.movement.paste_requested.connect(self._paste)
        self.movement.confirm_requested.connect(self._confirm)
        self.movement.move_requested.connect(self._move)
        self.movement.tilt_toggled.connect(self._set_tilt)
        self.movement.straight_toggled.connect(self._set_straight)
        self.movement.always_read_toggled.connect(self._set_always_read)
        self.calibration.points_changed.connect(self._calibration_changed)
        self.calibration.empty_point_changed.connect(self._empty_point_changed)
        self.calibration.status_message.connect(self._set_calibration_status)
        self.settings_tab.settings_saved.connect(self._settings_saved)
        self.settings_tab.status_message.connect(self._set_error_status)
        self.settings_tab.hotkey_change_requested.connect(self._start_learning)
        self.settings_tab.hotkey_clear_requested.connect(self._clear_hotkey)
        self.settings_tab.hotkeys_enabled_changed.connect(self._set_hotkeys_enabled)
        self.sizes.library_changed.connect(self._sizes_changed)
        self.sizes.status_message.connect(self._set_error_status)
        self.movement.size_selected.connect(self._size_selected)

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
        self._title_label = label("Mapper's Overlay Redux", widget_role="appTitle")
        # Заголовок в одну строку: окно узкое, и перенос «Mapper's Overlay / Redux»
        # съедал высоту шапки.
        self._title_label.setWordWrap(False)
        layout.addWidget(self._title_label)
        self._version_label = label(f"v{__version__}", widget_role="muted")
        self._version_label.setWordWrap(False)
        layout.addWidget(self._version_label)
        # «Мини» стоит рядом с названием, а не у правого края: там она читалась как кнопка
        # системного заголовка окна и спорила с бейджем калибровки.
        # Пилюля того же вида, что и бейдж калибровки: одинаковая высота и скругление.
        self._mini_button = button(
            "Мини",
            widget_role="badge",
            tooltip="Свернуть окно до крестовины и шага",
            accessible="Мини-версия окна",
        )
        self._mini_button.clicked.connect(self.toggle_mini)
        layout.addSpacing(ROW_SPACING)
        layout.addWidget(self._mini_button)
        layout.addStretch(1)
        self._calibration_label = label("", widget_role="badge")
        self._calibration_label.setWordWrap(False)
        layout.addWidget(self._calibration_label)
        return header

    def _refresh_header(self) -> None:
        settings = self._context.settings
        points = len(settings.calibration)
        empty = "есть" if settings.has_confirmation_point() else "нет"
        self._calibration_label.setText(f"Калибровка {points}/6 · F: {empty}")
        # Готовность калибровки — состояние, а не украшение: полная подсвечивается зелёным.
        role = (
            "badgeOk"
            if points == len(PANEL_ORDER) and settings.has_confirmation_point()
            else "badge"
        )
        self._calibration_label.setProperty("role", role)
        self._calibration_label.style().unpolish(self._calibration_label)
        self._calibration_label.style().polish(self._calibration_label)

    def status_text(self) -> str:
        """Текст строки состояния (для тестов и журнала)."""
        return self._status.text()

    def _set_status(self, text: str, kind: str = STATUS_INFO) -> None:
        if _status_key(text) != _status_key(self._status.text()):
            note("статус [%s]: %s", kind, text)
        self._status.setText(text)
        self._status.setProperty("role", STATUS_ROLES.get(kind, STATUS_ROLES[STATUS_INFO]))
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _set_calibration_status(self, text: str) -> None:
        self._set_status(text, STATUS_INFO)

    def _set_error_status(self, text: str) -> None:
        self._set_status(text, STATUS_ERROR)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - имя из Qt
        """Ctrl+Z отменяет шаг, Ctrl+Y (или Ctrl+Shift+Z) повторяет его."""
        if self._undo_shortcut(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def _undo_shortcut(self, event: QKeyEvent) -> bool:
        """Разобрать клавишу отмены; ``False`` — не наша, пусть обрабатывает Qt.

        В полях ввода Ctrl+Z правит набранный текст, а не шаги предмета: там своя отмена.
        """
        if self._learning is not None:
            return False
        modifiers = event.modifiers()
        if not modifiers & Qt.KeyboardModifier.ControlModifier:
            return False
        focus = self.focusWidget()
        if isinstance(focus, QLineEdit | QTextEdit | QAbstractSpinBox | QComboBox):
            return False
        key = event.key()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Z and not shift:
            return self.undo()
        if key == Qt.Key.Key_Y or (key == Qt.Key.Key_Z and shift):
            return self.redo()
        return False

    def _reset_session(self) -> None:
        self._session = None
        self._pose = None
        self._history.clear()
        self.movement.set_pose(None)
        self.movement.set_warning("")

    def _calibration_changed(self, points: object) -> None:
        calibration = cast("Mapping[Field, Point]", points)
        try:
            updated = self._context.settings.with_calibration(calibration)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        if not self._apply_settings(updated):
            return
        missing = self._context.settings.missing_points()
        if missing:
            titles = ", ".join(field.label for field in missing)
            self._set_status(f"Калибровка сохранена. Не хватает полей: {titles}", STATUS_WARN)
        else:
            self._set_status("Калибровка сохранена. Нажмите «Считать».")

    def _empty_point_changed(self, point: object) -> None:
        selected = cast("Point | None", point)
        try:
            updated = self._context.settings.with_empty_point(selected)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        if not self._apply_settings(updated):
            return
        if selected is None:
            self._set_status("Точка пустого места снята: «Сохранить F» недоступно", STATUS_WARN)
        else:
            self._set_status("Точка пустого места сохранена: «Сохранить F» готово.", STATUS_OK)

    def _settings_saved(self, settings: object) -> None:
        new_settings = cast(Settings, settings)
        if not self._apply_settings(new_settings):
            return
        self._set_status("Настройки сохранены. Нажмите «Считать» заново.", STATUS_OK)

    def _apply_settings(self, settings: Settings) -> bool:
        """Записать настройки и показать их во всех местах окна.

        Returns:
            ``True``, если файл записался; иначе в строке состояния уже ошибка.
        """
        try:
            self._context.save_settings(settings)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return False
        self._reset_session()
        self._always_read = settings.always_read_pose
        self.movement.set_always_read(settings.always_read_pose)
        self.movement.set_default_step(settings.default_step)
        self.calibration.set_points(settings.calibration)
        self.calibration.set_empty_point(settings.empty_point)
        self.settings_tab.set_base_settings(settings)
        self._apply_hotkeys(settings.hotkeys)
        self._refresh_header()
        return True

    def _stop_timers(self) -> None:
        """Погасить все таймеры окна: после закрытия они не должны срабатывать."""
        self._heartbeat.stop()
        self._num_lock_timer.stop()
        self._hold_timer.stop()
        self._deadline_timer.stop()
        self._busy_timer.stop()
        self._learn_timer.stop()
        self._held = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - имя из Qt
        """Снять хук и дождаться фоновой задачи, чтобы не оставить поток висеть."""
        note("окно закрывается: занято=%s", "да" if self._runner.is_busy() else "нет")
        self._stop_timers()
        if METRICS.save(metrics_path()):
            note("замеры фаз записаны: %s", METRICS.summary())
        self._hotkeys.stop_listening()
        self._runner.shutdown()
        super().closeEvent(event)


def _status_key(text: str) -> str:
    """Текст статуса без счётчика секунд: «Шаг… (3 с)» и «Шаг… (4 с)» — одно событие."""
    return STATUS_COUNTER.sub("", text)


STATUS_COUNTER = re.compile(r" \(\d+ с\)$")
