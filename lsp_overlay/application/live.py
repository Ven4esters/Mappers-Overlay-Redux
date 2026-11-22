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
LIVE_HOLD_TIMEOUT = 1.0
HOLD_EPSILON = 1e-6


class LiveMover:
    """Крутит шаги в отдельном потоке и после каждого шага пишет позу в панель.

    По умолчанию ``F`` не нажимается: значения остаются в полях и показывают, где предмет
    окажется, но само размещение не подтверждается. Включается только настройкой
    ``live_commit`` — тогда каждый шаг ещё и подтверждается.

    Панель отвечает не мгновенно, поэтому «плавность» — это непрерывная очередь шагов:
    пока клавиша зажата, поток делает шаг за шагом. Направление хранится одно:
    новое нажатие заменяет предыдущее, очередь не растёт.

    Отпускание клавиши может не дойти (потерялось событие, хук снят системой), поэтому
    кроме явного :meth:`release` есть страховка: если за ``hold_timeout`` секунд не было
    ни одного нового нажатия (а при удержании Windows исправно шлёт автоповтор), движение
    останавливается само. Кнопки оверлея двигают ровно один шаг — :meth:`step_once`.
    """

    def __init__(
        self,
        session: MappingSession,
        *,
        commit: bool = False,
        tick: float = LIVE_TICK,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        hold_timeout: float = LIVE_HOLD_TIMEOUT,
    ) -> None:
        self._session = session
        self._commit = commit
        self._tick = tick
        self._sleep = sleep
        self._clock = clock
        self._hold_timeout = hold_timeout
        self._lock = threading.Lock()
        self._direction: Direction | None = None
        self._step: float | None = None
        self._single: tuple[Direction, float | None] | None = None
        self._last_event = 0.0
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
    def hold_timeout(self) -> float:
        """Сколько секунд без событий клавиши считается отпусканием."""
        return self._hold_timeout

    def set_hold_timeout(self, seconds: float) -> None:
        """Меняет страховку от «залипшей» клавиши."""
        self._hold_timeout = seconds

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
            self._last_event = self._clock()

    def step_once(self, direction: Direction, step: float | None = None) -> None:
        """Один шаг без удержания: так работают кнопки-стрелки оверлея."""
        with self._lock:
            self._single = (direction, step)
            self._last_event = self._clock()

    def release(self) -> None:
        """Клавиша отпущена — движение прекращается."""
        with self._lock:
            self._direction = None
            self._last_event = self._clock()

    def _take_task(self) -> tuple[Direction, float | None] | None:
        """Берёт один шаг из очереди: удержание клавиши или одиночный шаг кнопки."""
        with self._lock:
            single = self._single
            self._single = None
            direction = self._direction
            step = self._step
            stuck = (
                direction is not None
                and self._clock() - self._last_event > self._hold_timeout + HOLD_EPSILON
            )
            if stuck:
                self._direction = None
                direction = None
        if stuck:
            LOGGER.warning(
                "Клавиша не отпустилась за %.1f с — движение остановлено", self._hold_timeout
            )
        if single is not None:
            return single
        if direction is None:
            return None
        return direction, step

    def _loop(self) -> None:
        while self._running:
            task = self._take_task()
            if task is None:
                self._sleep(self._tick)
                continue
            direction, step = task
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
            LOGGER.debug("Живой режим: шаг %d, %s", self._applied, direction.value)
            # пауза между шагами: панель и так отвечает не мгновенно, а горячий цикл
            # только жжёт процессор и забивает журнал записи
            self._sleep(self._tick)
