"""Структурированный журнал: одна операция — одна JSON-строка."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Final

LOG_FORMAT_VERSION: Final = 1


class JsonFormatter(logging.Formatter):
    """Форматтер JSON-строк с временем, уровнем, логгером и сообщением."""

    def format(self, record: logging.LogRecord) -> str:
        """Собрать одну JSON-строку из записи логгера."""
        payload: dict[str, Any] = {
            "v": LOG_FORMAT_VERSION,
            "time": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(path: Path, *, debug: bool = False, console: bool = False) -> None:
    """Настроить корневой логгер на запись в файл (и, при желании, в консоль)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JsonFormatter())
        root.addHandler(console_handler)
