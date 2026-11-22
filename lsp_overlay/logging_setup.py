"""Логи: JSON-строки в файл и короткий читаемый вывод в консоль."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "overlay.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3


class JsonFormatter(logging.Formatter):
    """Формат `{"time": ..., "level": ..., "logger": ..., "message": ...}`."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_dir: Path, *, debug: bool = False) -> Path:
    """Настраивает файловый и консольный обработчики, возвращает путь к файлу."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / LOG_FILE_NAME
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    root.addHandler(console)
    return log_path
