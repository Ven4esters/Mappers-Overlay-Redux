"""Главное окно оверлея: вкладки, сценарии, горячие клавиши."""

from __future__ import annotations

import logging
import re
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
from map_overlay.domain.keynames import COMMON_GAME_KEYS, VK_ESCAPE, VK_MENU, key_name
from map_overlay.domain.movement import COORD_DECIMALS
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose
from map_overlay.domain.sizes import SizeLibrary
from map_overlay.errors import ConfigError, ValidationError
from map_overlay.trace import note
from map_overlay.ui.appicon import icon as app_icon
from map_overlay.ui.tabs.calibration_tab import CalibrationTab
from map_overlay.ui.tabs.movement_tab import MovementTab, pose_text
from map_overlay.ui.tabs.settings_tab import SettingsTab
from map_overlay.ui.tabs.sizes_tab import SizesTab
from map_overlay.ui.tasks import TaskRunner
from map_overlay.ui.widgets import button, label

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 640
WINDOW_HEIGHT = 820
MINI_WIDTH = 380
MINI_HEIGHT = 430
# Мини-версия: крестовина, шаг и выбор предмета без прокрутки и переключения вкладок.
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
ACTION_DEADLINE_MS = 20000
# Сколько ждать обмен с панелью, прежде чем прервать его самим.
#
# Раньше зависший обмен оставлял окно занятым навсегда, и оверлей приходилось
# закрывать через диспетчер задач. Теперь по таймауту задача бросается автоматически.
STUCK_HINT_S = 5.0

UNFREEZE_WAIT_MS = 1500
# Сколько ждём выхода брошенного потока, прежде чем всё равно отпустить клавиатуру.

UNFREEZE_POLL_MS = 100
HOLD_REPEAT_MS = 150
# Пауза перед следующим шагом удержания: отсчитывается от конца предыдущего.

NUM_LOCK_CHECK_MS = 3000
# Как часто проверять NumLock: без него Numpad посылает другие клавиши.
LEARN_TIMEOUT_MS = 10_000
STATE_LOG_MS = 20_000
# Как часто писать «жив» со сводкой состояния: по этим строкам видно, что было
# до зависания, даже если сторож не успел снять стеки.


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
        self._tilt_mode = False
        self._num_lock_state: bool | None = None
        self._learn_timer = QTimer(self)
        self._learn_timer.setSingleShot(True)
        self._learn_timer.timeout.connect(self._learning_expired)
        self._mini = False
        self._normal_size: tuple[int, int] | None = None
        self._normal_tab = 0
        self._build()
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
            points=settings.calibration,
            empty_point=settings.empty_point,
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
        self._abort_button = button(
            "Прервать",
            widget_role="small",
            tooltip="Бросить текущее действие, если панель не отвечает",
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
        self.movement.confirm_requested.connect(self._confirm)
        self.movement.move_requested.connect(self._move)
        self.movement.tilt_toggled.connect(self._set_tilt)
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
        title = label("Mapper's Overlay Redux", widget_role="appTitle")
        # Заголовок в одну строку: окно узкое, и перенос «Mapper's Overlay / Redux»
        # съедал высоту шапки.
        title.setWordWrap(False)
        layout.addWidget(title)
        layout.addWidget(label(f"v{__version__}", widget_role="muted"))
        layout.addStretch(1)
        self._calibration_label = label("", widget_role="muted")
        self._calibration_label.setWordWrap(False)
        self._mini_button = button(
            "Мини",
            widget_role="small",
            tooltip="Свернуть окно до крестовины и шага",
        )
        self._mini_button.clicked.connect(self.toggle_mini)
        layout.addWidget(self._calibration_label)
        layout.addWidget(self._mini_button)
        return header

    def _refresh_header(self) -> None:
        settings = self._context.settings
        points = len(settings.calibration)
        empty = "есть" if settings.has_confirmation_point() else "нет"
        self._calibration_label.setText(f"Калибровка {points}/6 · F: {empty}")

    def toggle_mini(self) -> None:
        """Переключить обычный вид и мини-версию."""
        self.set_mini(not self._mini)

    def set_mini(self, enabled: bool) -> None:
        """Свернуть окно до мини-версии (крестовина и шаг) или вернуть полный вид.

        В мини-версии прячутся вкладки и подписи: остаётся только то, чем двигают
        предмет. Обратное переключение возвращает прежний размер и прежнюю вкладку.
        """
        if enabled == self._mini:
            return
        self._mini = enabled
        if enabled:
            self._normal_size = (self.width(), self.height())
            self._normal_tab = self._tabs.currentIndex()
            self._tabs.setCurrentIndex(0)
            self._tabs.tabBar().setVisible(False)
            self._calibration_label.setVisible(False)
            self._mini_button.setText("Обычный")
            self._mini_button.setToolTip("Вернуть полное окно: вкладки, калибровка, настройки")
            self.movement.set_compact(True)
            self._fit_layout()
            self.resize(MINI_WIDTH, MINI_HEIGHT)
        else:
            self._tabs.tabBar().setVisible(True)
            self._calibration_label.setVisible(True)
            self._mini_button.setText("Мини")
            self._mini_button.setToolTip("Свернуть окно до крестовины и шага")
            self.movement.set_compact(False)
            self._fit_layout()
            width, height = self._normal_size or (WINDOW_WIDTH, WINDOW_HEIGHT)
            self.resize(width, height)
            if 0 <= self._normal_tab < self._tabs.count():
                self._tabs.setCurrentIndex(self._normal_tab)

    def _fit_layout(self) -> None:
        """Пересчитать минимальный размер окна после скрытия части вкладки.

        Qt кэширует минимальный размер от раскладки: без пересчёта ``resize`` в мини-версии
        упирался в ширину полного окна, и мини-окно оставалось большим.
        """
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        # Сбросить минимальный размер, который Qt оставил от прежнего вида: он и не давал
        # окну стать уже. Раскладка оставит свой минимум сама на следующем проходе.
        self.setMinimumSize(0, 0)
        self.resize(self.minimumSizeHint())

    def press_mini(self) -> None:
        """Нажать «Мини»/«Обычный» (для тестов)."""
        self._mini_button.click()

    def is_mini(self) -> bool:
        """Включена ли мини-версия (для тестов)."""
        return self._mini

    def mini_button_text(self) -> str:
        """Надпись на переключателе мини-версии (для тестов)."""
        return self._mini_button.text()

    def tab_bar_visible(self) -> bool:
        """Видна ли строка вкладок (для тестов)."""
        return self._tabs.tabBar().isVisible()

    def tabs_index(self) -> int:
        """Номер текущей вкладки (для тестов)."""
        return self._tabs.currentIndex()

    def select_tab(self, index: int) -> None:
        """Переключить вкладку по номеру (для тестов)."""
        self._tabs.setCurrentIndex(index)

    def tab_fits(self, index: int) -> bool:
        """Помещается ли содержимое вкладки в окно по ширине (для тестов).

        Горизонтальная прокрутка выключена, поэтому всё, что шире окна, просто обрезается.
        Проверка ловит именно это: скрытые поля ввода и лишние кнопки раздували вкладку.
        """
        area = self._tabs.widget(index)
        if not isinstance(area, QScrollArea):
            return True
        content = area.widget()
        return content is None or content.width() <= area.viewport().width()

    def tab_titles(self) -> list[str]:
        """Названия вкладок по порядку."""
        return [self._tabs.tabText(index) for index in range(self._tabs.count())]

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

    def _set_busy(self, busy: bool) -> None:
        """Показать занятость и закрыть клавиатуру на время обмена с панелью.

        Заморозка нужна не для красоты: пока оверлей кликает по полю и посылает
        ``Ctrl+A``/``Ctrl+V``, случайное нажатие (например ``Alt+A``) дописывает в
        поле символ, значение перестаёт читаться, и обмен повторяется впустую.
        """
        self.movement.set_busy(busy)
        self._abort_button.setEnabled(busy)
        note("занятость: %s", "включена" if busy else "снята")
        if busy:
            self._hotkeys.freeze(True)
            self._busy_timer.start(BUSY_TICK_MS)
            self._deadline_timer.start(ACTION_DEADLINE_MS)
        else:
            self._busy_timer.stop()
            self._deadline_timer.stop()
            # Клавиатуру отпускаем только когда брошенный поток действительно вышел:
            # иначе нажатие попадёт в панель между кликом и вставкой. Ожидание ограничено.
            self._unfreeze_when_worker_stops()

    def _unfreeze_when_worker_stops(self, waited_ms: int = 0) -> None:
        """Отпустить клавиатуру, когда рабочий поток закончил (не дольше ``UNFREEZE_WAIT_MS``)."""
        if self._runner.is_worker_alive() and waited_ms < UNFREEZE_WAIT_MS:
            QTimer.singleShot(
                UNFREEZE_POLL_MS,
                lambda: self._unfreeze_when_worker_stops(waited_ms + UNFREEZE_POLL_MS),
            )
            return
        self._hotkeys.freeze(False)

    def _action_deadline(self) -> None:
        """Прервать обмен, который не уложился в отведённое время.

        Так окно не может «зависнуть» навсегда: даже если рабочий поток застрял,
        интерфейс разблокируется, клавиатура размораживается, а причина уходит в журнал.
        """
        if not self._runner.is_busy():
            return
        note(
            "дедлайн: обмен «%s» идёт %.1f с — прерываю",
            self._busy_text,
            self._runner.busy_seconds(),
        )
        logger.warning(
            "Обмен с панелью прерван по таймауту: «%s» шёл %.1f с",
            self._busy_text,
            self._runner.busy_seconds(),
        )
        self._stop_hold()
        self._cancel_running()
        self._set_busy(False)
        self._drop_pose("Панель не ответила за 20 с")
        self._set_status(
            "Действие прервано: панель не ответила за 20 с. Проверьте, что окно панели "
            "на экране и не перекрыто, и нажмите «Считать».",
            STATUS_WARN,
        )

    def _begin_busy(self, text: str) -> None:
        """Показать, что идёт обмен с панелью, и засечь время."""
        note("начато действие: %s", text)
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

    def _cancel_running(self) -> bool:
        """Остановить обмен: сначала попросить рабочий поток выйти, потом бросить задачу.

        Без сигнала отмены брошенный поток продолжал бы кликать и вставлять значения,
        пока не пройдёт все поля: панель получала бы чужие нажатия, а координаты —
        мусор. Отмена видна панели между шагами и завершает поток за один шаг.
        """
        if self._session is not None:
            self._session.cancel()
        return self._runner.abandon()

    def _abort_action(self) -> None:
        """Бросить зависшее действие, не закрывая окно."""
        self._stop_hold()
        note("нажата кнопка «Прервать»")
        if not self._cancel_running():
            note("прерывать нечего: обмена нет")
            return
        self._set_busy(False)
        self._drop_pose("Действие прервано вручную")
        self._set_status(
            "Действие прервано вручную, удержание остановлено. "
            "Клавиатура свободна. Нажмите «Считать», чтобы продолжить.",
            STATUS_WARN,
        )

    def _drop_pose(self, reason: str) -> None:
        """Забыть координаты: после сбоя двигаться от них нельзя."""
        if self._pose is None:
            return
        logger.warning("%s — координаты сброшены, нужен новый «Считать»", reason)
        self._pose = None
        self.movement.set_pose(None)

    def _ensure_session(self) -> MappingSession:
        if self._session is None:
            self._session = self._context.make_session()
        return self._session

    # --- действия ---------------------------------------------------------

    # --- библиотека размеров ----------------------------------------------

    def _sizes_changed(self, library: object) -> None:
        """Сохранить библиотеку размеров и обновить список предметов."""
        candidate = cast(SizeLibrary, library)
        try:
            self._context.save_sizes(candidate)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return
        self.sizes.set_library(candidate)
        self.movement.set_sizes(candidate)
        active = candidate.active_item
        suffix = f", выбран «{active.name}»" if active is not None else ""
        self._set_status(f"Размеры: предметов {len(candidate.items)}{suffix}", STATUS_OK)

    def _size_selected(self, name: object) -> None:
        """Запомнить выбранный предмет: из него берётся шаг."""
        selected = cast("str | None", name)
        try:
            library = self._context.sizes.select(selected)
            self._context.save_sizes(library)
        except (ConfigError, ValidationError) as exc:
            self._set_status(str(exc), STATUS_ERROR)
            self.movement.set_sizes(self._context.sizes)
            return
        self.sizes.set_library(library)
        self.movement.set_sizes(library)
        active = library.active_item
        if active is None:
            self._set_status("Предмет не выбран: шаг задаётся вручную.")
            return
        self._set_status(
            f"Выбран «{active.name}»: длина, ширина и половины подставляются в шаг кнопками.",
            STATUS_OK,
        )

    def _capture(self) -> None:
        note("команда: считать координаты")
        self._stop_hold()
        if self._runner.is_busy():
            note("считать не начато: занято «%s»", self._busy_text)
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
        note("команда: сохранить F")
        self._stop_hold()
        if self._runner.is_busy():
            note("сохранить F не начато: занято «%s»", self._busy_text)
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
        """Сделать шаг; ``tilt`` — режим высоты (клавиша Alt): 8 вверх, 2 вниз.

        Returns:
            ``True``, если задача поставлена: ``False`` — шаг невозможен.
        """
        if self._runner.is_busy():
            logger.info("Шаг не начат: занято другим действием")
            note("шаг не начат: занято другим действием")
            return False
        session = self._session
        if session is None or session.pose is None or self._pose is None:
            logger.warning("Шаг не начат: координаты не считаны")
            note("шаг не начат: координаты не считаны")
            self._set_status(
                "Сначала нажмите «Считать»: без координат шаг не посчитать", STATUS_WARN
            )
            return False
        selected = cast(Direction, direction)
        suffix = ""
        if tilt and selected in (Direction.FORWARD, Direction.BACK):
            suffix = " (вверх)" if selected is Direction.FORWARD else " (вниз)"
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
        self._schedule_hold_step()
        step_result = cast(StepResult, result)
        self._pose = step_result.pose
        self.movement.set_pose(step_result.pose)
        self.movement.set_warning(self._tilt_warning(step_result.pose))
        written = ", ".join(field.label for field in step_result.written) or "ничего"
        deltas = f"ΔX {format_delta(step_result.delta_x)} · ΔY {format_delta(step_result.delta_y)}"
        slope = ""
        if step_result.delta_z:
            deltas = f"{deltas} · ΔZ {format_delta(step_result.delta_z)}"
        if step_result.tilted:
            slope = " · Alt: вверх/вниз"
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
        if self._session is not None and self._session.pose is None:
            self._drop_pose(message)
            message = f"{message}. Нажмите «Считать» и повторите"
        self._set_status(message, STATUS_ERROR)

    def _tilt_warning(self, pose: Pose) -> str:
        """Подсказка про режим высоты: только когда он выключен и предмет наклонён."""
        if self._tilt_mode or not pose.has_tilt:
            return ""
        angles = " · ".join(
            f"{field.value.upper()} {format_value(pose.value(field), COORD_DECIMALS)}°"
            for field in (Field.RX, Field.RY)
            if abs(pose.value(field)) > 1e-9
        )
        return (
            f"{angles}: нажмите Alt — Num 8 будет поднимать предмет, Num 2 опускать. "
            "Сейчас они идут вперёд и назад."
        )

    # --- горячие клавиши --------------------------------------------------

    def _on_hotkey(self, vk: int, is_down: bool, fresh: bool = True) -> None:
        """Событие клавиатуры: сюда приходит даже автоповтор зажатой клавиши."""
        repeat = " (автоповтор)" if is_down and not fresh else ""
        note("клавиша %s %s%s", key_name(vk), "нажата" if is_down else "отпущена", repeat)
        if not self.settings_tab.hotkeys_enabled():
            logger.debug("Клавиша %s: перехват выключен", key_name(vk))
            note("клавиша %s пропущена: перехват выключен", key_name(vk))
            return
        if self._learning is not None:
            if is_down:
                self._finish_learning(vk)
            return
        if vk == VK_MENU and is_down and fresh:
            self._toggle_tilt()
            return
        action = self._router.handle(vk, is_down, fresh)
        if action is not None:
            logger.info("Клавиша %s → %s", key_name(vk), action.label)
            note("клавиша %s → команда «%s»", key_name(vk), action.label)
            self._dispatch(action, vk)
            return
        if not is_down:
            self._release_key(vk)

    def _refresh_tilt_warning(self) -> None:
        """Подсказка про режим высоты зависит от того, включён он или нет."""
        pose = self._pose
        self.movement.set_warning("" if pose is None else self._tilt_warning(pose))

    def _toggle_tilt(self) -> None:
        """Переключить режим высоты: Alt нажимают один раз, а не держат.

        Держать Alt нельзя: пока он зажат, игра не применяет правки панели к
        объекту — значения доходят до интерфейса и теряются.
        """
        self._set_tilt(not self._tilt_mode)

    def _set_tilt(self, enabled: bool) -> None:
        if enabled == self._tilt_mode:
            return
        self._tilt_mode = enabled
        note("режим высоты: %s", "включён" if enabled else "выключен")
        self.movement.set_tilt(enabled)
        self._refresh_tilt_warning()
        if enabled:
            logger.info("Режим высоты включён")
            self._set_status(
                "Режим высоты включён: Num 8 — вверх, Num 2 — вниз. Остальные клавиши "
                "работают как обычно. Alt — выключить.",
                STATUS_OK,
            )
        else:
            logger.info("Режим высоты выключен")
            self._set_status("Режим высоты выключен: Num 8 — вперёд, Num 2 — назад.")

    def _dispatch(self, action: Action, vk: int) -> None:
        if action is Action.CAPTURE:
            self._capture()
            return
        if action is Action.CONFIRM:
            self._confirm()
            return
        if action.direction is not None:
            if self._hotkeys.key_down(VK_MENU) and not self._tilt_mode:
                # Привычка «Alt + направление» тоже включает режим.
                self._set_tilt(True)
            self._start_hold(action, vk)

    # --- удержание направления -------------------------------------------

    def _start_hold(self, action: Action, vk: int) -> None:
        """Начать удержание: первый шаг сразу, следующие — друг за другом."""
        self._stop_hold()
        self._held = (action, vk)
        note("удержание: %s (клавиша %s)", action.label, key_name(vk))
        self._hold_tick(force=True)

    def _hold_tick(self, *, force: bool = False) -> None:
        """Сделать очередной шаг удержания.

        ``force`` — вызов из самого нажатия: событие уже доказывает, что клавишу
        нажали, поэтому состояние клавиши не перепроверяется. Без этого быстрое
        нажатие не давало шага вовсе.

        Следующий шаг ставится не по общему таймеру, а после завершения текущего
        (:meth:`_schedule_hold_step`): один шаг занимает около секунды, и обмен
        с панелью сам задаёт темп — движение идёт без пауз и рывков.
        """
        held = self._held
        if held is None:
            self._hold_timer.stop()
            return
        action, vk = held
        if not self.settings_tab.hotkeys_enabled():
            self._stop_hold()
            return
        if not force and not self._hotkeys.key_down(vk):
            logger.debug("Удержание %s снято: клавиша не нажата", action.label)
            self._stop_hold()
            return
        if force and self._hotkeys.key_down(VK_MENU):
            logger.warning(
                "Alt зажат во время шага: игра может не применить изменение. "
                "Режим высоты включается одним нажатием Alt"
            )
        if self._runner.is_busy():
            return
        if not self._step_once(action):
            self._stop_hold()

    def _schedule_hold_step(self) -> None:
        """Поставить следующий шаг удержания сразу после завершения текущего."""
        if self._held is not None:
            self._hold_timer.start(HOLD_REPEAT_MS)

    def _step_once(self, action: Action) -> bool:
        direction = action.direction
        if direction is None:
            return False
        try:
            step = self.movement.current_step()
        except ValidationError as exc:
            logger.warning("Шаг не начат: %s", exc)
            self._set_status(str(exc), STATUS_WARN)
            return False
        return self._move(direction, step, tilt=self._tilt_mode)

    def _release_key(self, vk: int) -> None:
        """Отпускание клавиши прекращает удержание."""
        if self._held is not None and self._held[1] == vk:
            self._stop_hold()

    def _stop_hold(self) -> None:
        if self._held is not None:
            note("удержание остановлено: %s", self._held[0].label)
        self._hold_timer.stop()
        self._held = None

    def _start_learning(self, action: object) -> None:
        self._stop_hold()
        if not self.settings_tab.hotkeys_enabled():
            self._set_status("Перехват клавиш выключен — назначить клавишу нельзя.", STATUS_WARN)
            return
        selected = cast(Action, action)
        note("назначение клавиши для «%s»: жду нажатия", selected.label)
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
        self._router.reset()
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
        self._router.reset()
        self._hotkeys.configure(
            bound_keys=self._router.bound_keys, learning=self._learning is not None
        )
        self.settings_tab.set_hotkeys(hotkeys)

    def _log_state(self) -> None:
        """Записать «жив» со сводкой: что происходит прямо сейчас."""
        pose = self._pose
        note(
            "жив: занято=%s%s, шаг=%s, удержание=%s, высота=%s, координаты=%s",
            "да" if self._runner.is_busy() else "нет",
            f" ({self._busy_text}, {self._runner.busy_seconds():.0f} с)"
            if self._runner.is_busy()
            else "",
            self.movement.step_text(),
            self._held[0].label if self._held is not None else "нет",
            "вкл" if self._tilt_mode else "выкл",
            pose_text(pose) if pose is not None else "не считаны",
        )

    def _check_num_lock(self) -> None:
        """Следить за NumLock: без него Numpad посылает «стрелки», а не цифры."""
        state = self._hotkeys.num_lock_enabled()
        if state == self._num_lock_state:
            return
        self._num_lock_state = state
        if state is False:
            warning = (
                "NumLock выключен: цифровой блок работает как навигация, "
                "горячие клавиши не сработают."
            )
            logger.warning("NumLock выключен: Numpad посылает другие клавиши")
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
        self._hotkeys.stop_listening()
        self._runner.shutdown()
        super().closeEvent(event)


def _status_key(text: str) -> str:
    """Текст статуса без счётчика секунд: «Шаг… (3 с)» и «Шаг… (4 с)» — одно событие."""
    return STATUS_COUNTER.sub("", text)


STATUS_COUNTER = re.compile(r" \(\d+ с\)$")
