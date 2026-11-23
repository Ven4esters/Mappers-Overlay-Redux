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
