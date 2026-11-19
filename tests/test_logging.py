"""Logging tests: redaction and file handler. / Тесты логов и маскировки."""

from __future__ import annotations

import logging

from app.logging_setup import RedactingFormatter, log_path, redact, setup_logging

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz-_0123456789"


def test_redact_masks_webhook_token() -> None:
    assert WEBHOOK not in redact(f"failed to post via {WEBHOOK} (HTTP 500)")
    redacted = redact(WEBHOOK)
    assert "webhooks/123456789012345678/" in redacted
    assert "AbCdEfGh" not in redacted
    # partial exposure in the middle of a sentence
    assert "AbCdEfGh" not in redact(f"GET {WEBHOOK}")


def test_redact_masks_secretish_values() -> None:
    assert "hunter2secret" not in redact("client_secret: hunter2secret")
    assert "topsecretvalue" not in redact('"access_token": "topsecretvalue"')
    assert "keepme" not in redact("password=keepme123")


def test_redacting_formatter_applies_to_full_record() -> None:
    formatter = RedactingFormatter("%(message)s")
    record = logging.LogRecord("screensaver.test", logging.INFO, __file__, 1,
                               "POST %s", (WEBHOOK,), None)
    rendered = formatter.format(record)
    assert WEBHOOK not in rendered
    assert "••••••" in rendered


def test_setup_logging_writes_rotating_file(tmp_path) -> None:
    path = setup_logging(tmp_path)
    logger = logging.getLogger("screensaver.test_setup")
    logger.info("test message via %s", WEBHOOK)
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = path.read_text(encoding="utf-8")
    assert "test message via" in content
    assert WEBHOOK not in content
    assert path.name == "screensaver.log"


def test_log_path_default_and_override(tmp_path) -> None:
    assert log_path(tmp_path) == tmp_path / "screensaver.log"
    assert log_path().name == "screensaver.log"
