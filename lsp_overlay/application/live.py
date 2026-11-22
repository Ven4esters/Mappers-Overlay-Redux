"""Живой режим: объект (или его копия) двигается в игре в реальном времени."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from lsp_overlay.application.session import MappingSession
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.errors import DomainError

LOGGER = logging.getLogger(__name__)
LIVE_TICK = 0.05
JOIN_TIMEOUT = 2.0


class LiveMover:
    """Крутит шаги в отдельном потоке и после каждого шага пишет позу в панель.

    По умолчанию ``F`` не нажимается: значения остаются в полях и показывают, где предмет
    окажется, но само размещение не подтверждается. Включается только настройкой
    ``live_commit`` — тогда каждый шаг ещё и подтверждается.

    Панель отвечает не мгновенно, поэтому «плавность» — это непрерывная очередь шагов:
    пока клавиша зажата, поток делает шаг за шагом. Направление хранится одно:
    новое нажатие заменяет предыдущее, очередь не растёт.
    """

    def __init__(
        self,
        session: MappingSession,
        *,
        commit: bool = False,
        tick: float = LIVE_TICK,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session
        self._commit = commit
        self._tick = tick
        self._sleep = sleep
        self._lock = threading.Lock()
        self._direction: Direction | None = None
        self._step: float | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._applied = 0
        self._error: str | None = None

    @property
    def is_running(self) -> bool:
        """Поток живого режима запущен."""
        return self._running

    @property
    def applied(self) -> int:
        """Сколько шагов уже ушло в игру."""
        return self._applied

    @property
    def last_error(self) -> str | None:
        """Последняя ошибка записи (живой режим её не глотает)."""
        return self._error

    @property
    def commit(self) -> bool:
        """Подтверждается ли каждый шаг клавишей ``F``."""
        return self._commit

    def set_commit(self, commit: bool) -> None:
        """Переключает подтверждение (на лету, без перезапуска потока)."""
        self._commit = commit

    @property
    def direction(self) -> Direction | None:
        """Направление, которое сейчас отрабатывается."""
        return self._direction

    def start(self) -> None:
        """Запускает поток."""
        if self._running:
            return
        self._error = None
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="live-mover", daemon=True)
        self._thread.start()
        LOGGER.info("Живой режим запущен")

    def stop(self) -> None:
        """Останавливает поток; последний шаг доделывается до конца."""
        if not self._running:
            return
        self._running = False
        with self._lock:
            self._direction = None
        thread = self._thread
        if thread is not None:
            thread.join(JOIN_TIMEOUT)
        self._thread = None
        LOGGER.info("Живой режим остановлен, шагов в игре: %d", self._applied)

    def steer(self, direction: Direction, step: float | None = None) -> None:
        """Задаёт направление движения (аналог зажатой клавиши)."""
        with self._lock:
            self._direction = direction
            self._step = step

    def release(self) -> None:
        """Клавиша отпущена — движение прекращается."""
        with self._lock:
            self._direction = None

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                direction = self._direction
                step = self._step
            if direction is None:
                self._sleep(self._tick)
                continue
            try:
                self._session.move(direction, step)
                self._session.apply(commit=self._commit)
            except DomainError as error:
                LOGGER.warning("Живой режим остановлен: %s", error)
                with self._lock:
                    self._error = str(error)
                    self._direction = None
                continue
            self._applied += 1
            # пауза между шагами: панель и так отвечает не мгновенно, а горячий цикл
            # только жжёт процессор и забивает журнал записи
            self._sleep(self._tick)
