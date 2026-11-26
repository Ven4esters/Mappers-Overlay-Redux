"""Журнал: JSON-строки с уровнем и сообщением."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from map_overlay.logging_setup import setup_logging


def test_setup_logging_writes_json(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "overlay.log"
    setup_logging(path)
    logging.getLogger("test").warning("проверка журнала")
    for handler in logging.getLogger().handlers:
        handler.flush()
    line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["level"] == "WARNING"
    assert payload["message"] == "проверка журнала"
    assert payload["logger"] == "test"


def test_setup_keeps_foreign_handlers(tmp_path) -> None:
    from map_overlay.logging_setup import setup_logging

    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    try:
        setup_logging(tmp_path / "overlay.log")
        assert foreign in root.handlers
    finally:
        root.removeHandler(foreign)


def test_log_rotates_instead_of_growing(tmp_path: Path) -> None:
    """Журнал ограничен по размеру: файл не растёт до бесконечности."""
    from logging.handlers import RotatingFileHandler

    from map_overlay import logging_setup

    path = tmp_path / "overlay.log"
    setup_logging(path)
    handlers = [
        item for item in logging.getLogger().handlers if isinstance(item, RotatingFileHandler)
    ]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == logging_setup.LOG_MAX_BYTES
    assert handler.backupCount == logging_setup.LOG_BACKUP_COUNT

    handler.maxBytes = 200  # ускоряем поворот, не дожидаясь мегабайтов
    for index in range(20):
        logging.getLogger("rotate").warning("строка номер %d для поворота журнала", index)
    handler.flush()
    assert path.with_suffix(".log.1").exists()


def test_file_log_keeps_debug_by_default(tmp_path: Path) -> None:
    """Подробности нужны без флага --debug: иначе зависать будет «молча»."""
    path = tmp_path / "overlay.log"
    setup_logging(path)
    logging.getLogger("map_overlay.action").debug("подробная строка")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "подробная строка" in path.read_text(encoding="utf-8")


def _console_levels() -> list[int]:
    """Уровни консольных обработчиков, которые поставил сам оверлей."""
    from logging.handlers import RotatingFileHandler

    from map_overlay import logging_setup

    return [
        handler.level
        for handler in logging_setup._OWN_HANDLERS
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, RotatingFileHandler)
    ]


def test_console_stays_quiet_without_debug(tmp_path: Path) -> None:
    setup_logging(tmp_path / "overlay.log", console=True)
    assert _console_levels() == [logging.INFO]


def test_console_is_verbose_with_debug(tmp_path: Path) -> None:
    setup_logging(tmp_path / "overlay.log", console=True, debug=True)
    assert _console_levels() == [logging.DEBUG]


def test_correlation_id_marks_operation(tmp_path: Path) -> None:
    """Все строки одной операции несут один correlation_id — так они ищутся вместе."""
    import logging as logging_module

    from map_overlay.logging_setup import correlation_scope

    path = tmp_path / "overlay.log"
    setup_logging(path)
    with correlation_scope("step") as operation:
        logging_module.getLogger("test").info("первая строка")
        logging_module.getLogger("test").warning("вторая строка")
    logging_module.getLogger("test").info("вне операции")
    for handler in logging_module.getLogger().handlers:
        handler.flush()
    payloads = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert payloads[0]["correlation_id"] == operation
    assert payloads[1]["correlation_id"] == operation
    assert "correlation_id" not in payloads[2]


def test_nested_scope_keeps_outer_operation() -> None:
    from map_overlay.logging_setup import correlation_scope, current_correlation_id

    with correlation_scope("outer") as outer, correlation_scope("inner") as inner:
        assert inner == outer
        assert current_correlation_id() == outer
    assert current_correlation_id() == ""


def test_timed_operation_sets_correlation(tmp_path: Path) -> None:
    """Замер операции — та же единица работы: журнал панели попадает под тот же id."""
    from map_overlay import logging_setup
    from map_overlay.trace import timed

    path = tmp_path / "overlay.log"
    setup_logging(path)
    with timed("проверка операции", slow_ms=10_000):
        marker = logging_setup.current_correlation_id()
        logging.getLogger("panel").info("обмен с панелью")
    for handler in logging.getLogger().handlers:
        handler.flush()
    payloads = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    panel_lines = [item for item in payloads if item["logger"] == "panel"]
    assert marker
    assert panel_lines[0]["correlation_id"] == marker
