"""Журнал действий: последние события в памяти и подробный DEBUG в ``overlay.log``.

Зачем это нужно. Когда оверлей «зависает», в обычном журнале видно только последнюю
строку — и почти никогда не видно, на чём именно он встал. Поэтому каждое заметное
действие (нажатие клавиши, обмен с панелью, клик, вставка, смена статуса) пишется здесь:

* в ``overlay.log`` — строкой DEBUG, если запуск с подробным журналом, и всегда в память;
* в кольцевой журнал :data:`JOURNAL` — последние :data:`MAX_EVENTS` событий. Их печатает
  сторож зависаний в ``crash.log`` вместе со стеками потоков: по последним строкам видно,
  какая операция началась и не закончилась.

Пара «начал/готово» у :func:`timed` — главный инструмент: «начал» без «готово» и есть
место зависания.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Final

MAX_EVENTS: Final = 150
# Сколько последних действий держим в памяти. Хватает на несколько полных шагов.

SLOW_OP_MS: Final = 1200.0
# Дольше этого одна операция быть не должна: обмен с панелью занимает десятки-сотни мс.
# Медленная операция попадает в журнал предупреждением — её видно и без зависания.

logger = logging.getLogger("map_overlay.action")


@dataclass(frozen=True, slots=True)
class Event:
    """Одно действие: когда, в каком потоке и что именно."""

    seconds: float
    """Монотонное время: по нему считаются смещения между событиями."""

    moment: str
    """Время суток ``ЧЧ:ММ:СС.мск`` — чтобы сопоставить с остальным журналом."""

    thread: str
    """Имя потока: интерфейс, рабочий поток задачи или сторож."""

    text: str
    """Что произошло."""

    def line(self, base: float) -> str:
        """Строка для файла аварий: время, смещение, поток, текст."""
        return (
            f"{self.moment} +{(self.seconds - base) * 1000:7.0f} мс  " f"{self.thread}: {self.text}"
        )


class Journal:
    """Кольцевой журнал действий: помнит последние ``limit`` событий."""

    def __init__(self, limit: int = MAX_EVENTS) -> None:
        self._events: deque[Event] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def add(self, text: str) -> None:
        """Запомнить действие."""
        event = Event(
            seconds=time.monotonic(),
            moment=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            thread=_thread_name(),
            text=text,
        )
        with self._lock:
            self._events.append(event)

    def clear(self) -> None:
        """Забыть всё (для тестов и нового запуска)."""
        with self._lock:
            self._events.clear()

    def events(self) -> tuple[Event, ...]:
        """События по порядку: от старого к новому."""
        with self._lock:
            return tuple(self._events)

    def describe(self) -> str:
        """Последние действия текстом; пусто — понятная строка вместо ничего."""
        events = self.events()
        if not events:
            return "Действий не записано"
        base = events[0].seconds
        return "\n".join(event.line(base) for event in events)


def _thread_name() -> str:
    """Имя потока для журнала: у потоков Qt своего имени нет — «Dummy-N» непонятно."""
    name = threading.current_thread().name
    return "рабочий поток" if name.startswith("Dummy-") else name


JOURNAL: Final = Journal()
# Один журнал на процесс: его читает сторож зависаний из другого потока.


def note(template: str, *args: object) -> None:
    """Записать действие: в журнал модуля (DEBUG) и в память для файла аварий."""
    message = template % args if args else template
    logger.debug("%s", message)
    JOURNAL.add(message)


def note_slow(label: str, elapsed_ms: float) -> None:
    """Записать медленную операцию: предупреждением в журнал и в память."""
    logger.warning("Медленная операция: %s — %.0f мс", label, elapsed_ms)
    JOURNAL.add(f"медленно: {label} — {elapsed_ms:.0f} мс")


@contextmanager
def timed(label: str, *, slow_ms: float = SLOW_OP_MS) -> Iterator[None]:
    """Замерить операцию: «начал» и «готово» в журнале, медленные — предупреждением.

    Args:
        label: что делаем — попадает в журнал как есть.
        slow_ms: порог медленной операции в миллисекундах.
    """
    note("начал: %s", label)
    started = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms >= slow_ms:
            note_slow(label, elapsed_ms)
        else:
            note("готово: %s — %.0f мс", label, elapsed_ms)
