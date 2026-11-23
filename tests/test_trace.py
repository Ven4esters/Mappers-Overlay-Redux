"""Журнал действий: кольцевая память, метки времени и медленные операции."""

from __future__ import annotations

import logging
import time

from map_overlay import trace
from map_overlay.trace import JOURNAL, Journal, note, note_slow, timed


def test_note_keeps_event_and_moment() -> None:
    journal = Journal()
    journal.add("проверка")
    (event,) = journal.events()
    assert event.text == "проверка"
    assert event.thread == "MainThread"
    assert len(event.moment) == len("12:34:56.789")


def test_journal_keeps_only_the_last_events() -> None:
    journal = Journal(limit=3)
    for index in range(5):
        journal.add(f"шаг {index}")
    assert [event.text for event in journal.events()] == ["шаг 2", "шаг 3", "шаг 4"]


def test_journal_clear() -> None:
    journal = Journal()
    journal.add("что-то")
    journal.clear()
    assert journal.events() == ()


def test_describe_numbers_events() -> None:
    journal = Journal()
    journal.add("первое")
    journal.add("второе")
    text = journal.describe()
    lines = text.splitlines()
    assert len(lines) == 2
    assert "первое" in lines[0]
    assert "второе" in lines[1]
    assert "+" in lines[0] and "мс" in lines[0]


def test_describe_empty_journal() -> None:
    assert Journal().describe() == "Действий не записано"


def test_note_formats_and_records(caplog: logging.LogRecord) -> None:
    """Глобальный журнал видят другие потоки: сторож зависаний читает именно его."""
    JOURNAL.clear()
    with caplog.at_level(logging.DEBUG, logger="map_overlay.action"):
        note("поле %s = %s", "X", 1.5)
    assert "поле X = 1.5" in caplog.text
    assert "поле X = 1.5" in trace.JOURNAL.describe()


def test_timed_writes_start_and_finish() -> None:
    JOURNAL.clear()
    with timed("проверка операции"):
        pass
    text = JOURNAL.describe()
    assert "начал: проверка операции" in text
    assert "готово: проверка операции" in text


def test_timed_reports_slow_operation(caplog: logging.LogRecord) -> None:
    JOURNAL.clear()
    with (
        caplog.at_level(logging.WARNING, logger="map_overlay.action"),
        timed("медленная операция", slow_ms=0.0),
    ):
        time.sleep(0.001)
    assert "Медленная операция" in caplog.text
    assert "медленно: медленная операция" in JOURNAL.describe()


def test_timed_keeps_going_after_error() -> None:
    JOURNAL.clear()
    try:
        with timed("падающая операция"):
            raise ValueError("бум")
    except ValueError:
        pass
    # «готово» пишется и при ошибке: по нему видно, что операция закончилась.
    assert "готово: падающая операция" in JOURNAL.describe()


def test_note_slow_is_warning(caplog: logging.LogRecord) -> None:
    JOURNAL.clear()
    with caplog.at_level(logging.WARNING, logger="map_overlay.action"):
        note_slow("клик", 2500.0)
    assert "2500" in caplog.text
    assert "медленно: клик" in JOURNAL.describe()
