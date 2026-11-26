"""Общая основа окна: что у него есть и какие правила действуют во всех его частях.

Главное окно разделено по сценариям (``window_layout``, ``window_actions``,
``window_movement``, ``window_hotkeys``), но состояние у них одно — поза, история,
занятость, хук клавиатуры. Дублировать его по частям нельзя: шаг и удержание читают
``_pose``, отмена смотрит ``_session``, строка состояния одна на всё окно.

Поэтому части — это миксины с общей базой ``WindowBase``. База объявляет поля и связи
между сценариями: так каждая часть видит, что ей даёт соседняя, а ``mypy`` проверяет их
как одно целое. Здесь же — константы, которые относятся к окну целиком: статусы и
выдержки таймеров.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QTabWidget

from map_overlay.application.history import Change, History
from map_overlay.application.hotkeys import HotkeyRouter
from map_overlay.application.ports import HotkeySource
from map_overlay.application.session import MappingSession
from map_overlay.config import Settings
from map_overlay.context import AppContext
from map_overlay.domain.actions import Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.pose import Pose
from map_overlay.ui.tabs.calibration_tab import CalibrationTab
from map_overlay.ui.tabs.movement_tab import MovementTab
from map_overlay.ui.tabs.settings_tab import SettingsTab
from map_overlay.ui.tabs.sizes_tab import SizesTab
from map_overlay.ui.tasks import TaskRunner

STATUS_INFO: Final = "info"
STATUS_OK: Final = "ok"
STATUS_WARN: Final = "warn"
STATUS_ERROR: Final = "error"
STATUS_ROLES: Final[dict[str, str]] = {
    STATUS_INFO: "muted",
    STATUS_OK: "ok",
    STATUS_WARN: "warn",
    STATUS_ERROR: "error",
}

HOOK_CHECK_MS: Final = 800
HEARTBEAT_MS: Final = 250
BUSY_TICK_MS: Final = 500
ACTION_DEADLINE_MS: Final = 20000
# Сколько ждать обмен с панелью, прежде чем прервать его самим.
#
# Раньше зависший обмен оставлял окно занятым навсегда, и оверлей приходилось
# закрывать через диспетчер задач. Теперь по таймауту задача бросается автоматически.
STUCK_HINT_S: Final = 5.0

UNFREEZE_WAIT_MS: Final = 1500
# Сколько ждём выхода брошенного потока, прежде чем всё равно отпустить клавиатуру.

UNFREEZE_POLL_MS: Final = 100
HOLD_REPEAT_MS: Final = 150
# Пауза перед следующим шагом удержания: отсчитывается от конца предыдущего.

NUM_LOCK_CHECK_MS: Final = 3000
# Как часто проверять NumLock: без него Numpad посылает другие клавиши.
LEARN_TIMEOUT_MS: Final = 10_000
STATE_LOG_MS: Final = 20_000
# Как часто писать «жив» со сводкой состояния: по этим строкам видно, что было
# до зависания, даже если сторож не успел снять стеки.


class WindowBase(QMainWindow):
    """Общее состояние окна и объявления связей между его частями.

    Поля заполняет ``MainWindow.__init__``. Методы-заглушки здесь не вызываются: их
    реализуют миксины, которые стоят в MRO раньше базы. Заглушки нужны, чтобы каждая
    часть видела соседние сценарии и проверялась ``mypy``.
    """

    _context: AppContext
    _runner: TaskRunner
    _router: HotkeyRouter
    _hotkeys: HotkeySource
    _session: MappingSession | None
    _pose: Pose | None
    _history: History
    _pending_kind: str | None
    _pending_change: Change | None
    _last_request: tuple[Direction, float, bool, bool] | None
    _busy_text: str
    _held: tuple[Action, int] | None
    _refresh_on_step: bool
    _tilt_mode: bool
    _straight: bool
    _always_read: bool
    _num_lock_state: bool | None
    _learning: Action | None
    _mini: bool
    _normal_size: tuple[int, int] | None
    _normal_tab: int
    _tabs: QTabWidget
    _status: QLabel
    _title_label: QLabel
    _version_label: QLabel
    _calibration_label: QLabel
    _abort_button: QPushButton
    _mini_button: QPushButton
    _busy_timer: QTimer
    _deadline_timer: QTimer
    _hold_timer: QTimer
    _learn_timer: QTimer
    _num_lock_timer: QTimer
    _state_timer: QTimer
    _heartbeat: QTimer
    movement: MovementTab
    calibration: CalibrationTab
    settings_tab: SettingsTab
    sizes: SizesTab

    # --- связи между сценариями -------------------------------------------
    # Объявлены здесь, реализованы в миксинах: так каждая часть видит соседнюю.

    def _set_status(self, text: str, kind: str = STATUS_INFO) -> None:
        raise NotImplementedError

    def _apply_settings(self, settings: Settings) -> bool:
        raise NotImplementedError

    def _stop_hold(self) -> None:
        raise NotImplementedError

    def _set_busy(self, busy: bool) -> None:
        raise NotImplementedError

    def _begin_busy(self, text: str) -> None:
        raise NotImplementedError

    def _check_step_ready(self, what: str) -> bool:
        raise NotImplementedError

    def _drop_pose(self, reason: str) -> None:
        raise NotImplementedError

    def _ensure_session(self) -> MappingSession:
        raise NotImplementedError

    def _set_tilt(self, enabled: bool) -> None:
        raise NotImplementedError

    def _toggle_tilt(self) -> None:
        raise NotImplementedError

    def _start_hold(self, action: Action, vk: int) -> None:
        raise NotImplementedError

    def _release_key(self, vk: int) -> None:
        raise NotImplementedError

    def _capture(self) -> None:
        raise NotImplementedError

    def _paste(self, source: Pose | None = None) -> bool:
        raise NotImplementedError

    def _confirm(self) -> None:
        raise NotImplementedError

    def undo(self) -> bool:
        """Отменить последний шаг (реализуется в части движения)."""
        raise NotImplementedError

    def redo(self) -> bool:
        """Повторить отменённый шаг (реализуется в части движения)."""
        raise NotImplementedError

    def _apply_hotkeys(self, hotkeys: Mapping[Action, int | None]) -> None:
        raise NotImplementedError
