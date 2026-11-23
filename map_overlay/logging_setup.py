"""Структурированный журнал: одна операция — одна JSON-строка."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Final

LOG_FORMAT_VERSION: Final = 1
LOG_MAX_BYTES: Final = 2 * 1024 * 1024
# Сколько места журнал может занять: старые записи вытесняются, диск не переполняется.
LOG_BACKUP_COUNT: Final = 3

_OWN_HANDLERS: list[logging.Handler] = []
# Обработчики, добавленные этим модулем: чужие (например, в тестах) не трогаем.


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
    """Настроить корневой логгер на запись в файл (и, при желании, в консоль).

    Файл всегда пишет DEBUG: без подробных строк по журналу не понять, на чём именно
    оверлей завис. Объём ограничен поворотом (2 МиБ × 3), поэтому подробности не
    переполняют диск. Консоль, наоборот, по умолчанию молчит до INFO — иначе запуск
    из консоли превращается в поток служебных строк.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(_OWN_HANDLERS):
        root.removeHandler(handler)
        handler.close()
    _OWN_HANDLERS.clear()
    file_handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)
    _OWN_HANDLERS.append(file_handler)
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        console_handler.setFormatter(JsonFormatter())
        root.addHandler(console_handler)
        _OWN_HANDLERS.append(console_handler)
