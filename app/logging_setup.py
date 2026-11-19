"""Logging: rotating file + console, with secret redaction. / Логи + маскировка секретов.

The log lives at ``DATA_DIR / screensaver.log`` (next to ``main.py`` when the
folder is writable, otherwise in the OS app-data dir). Nothing is logged that
can carry a Discord token: webhook URLs and secret-ish values are redacted by
the formatter — handlers included.
Журнал — ``DATA_DIR / screensaver.log``. Ничего секретного: URL вебхуков и
ключи вырезаются форматтером до записи в любой обработчик.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "screensaver.log"

_WEBHOOK_RE = re.compile(r"(webhooks/\d{10,25}/)[^/\s\"?&<>'\])]{6,}", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?i)(client_secret|access_token|refresh_token|secret|password)([\"']?\s*[:=]\s*[\"']?)[^\s\"',&]{4,}")


def redact(text: object) -> str:
    """Mask Discord webhook tokens and secret-ish values. / Скрыть токены и ключи."""
    cleaned = _WEBHOOK_RE.sub(r"\1••••••", str(text))
    return _SECRET_RE.sub(r"\1\2••••••", cleaned)


class RedactingFormatter(logging.Formatter):
    """Formats a record, redacting secrets from the final message. / Форматтер с маской."""

    def format(self, record: logging.LogRecord) -> str:
        message = redact(record.getMessage())
        record.msg = message
        record.args = ()
        return super().format(record)


def log_path(log_dir: Path | None = None) -> Path:
    from app.paths import DATA_DIR

    root = Path(log_dir) if log_dir is not None else DATA_DIR
    return root / LOG_FILE_NAME


def setup_logging(log_dir: Path | None = None) -> Path:
    """Configure file + console handlers; returns the log file path.
    Настроить файловый и консольный обработчики; вернуть путь к журналу."""
    path = log_path(log_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    fmt = RedactingFormatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(fmt)
    root.addHandler(console)

    # httpx/httpcore log full URLs (which carry tokens) — keep them quiet + redacted anyway
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
