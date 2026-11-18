"""Webhook URL validation/parsing. / Валидация и разбор URL вебхука.

Discord webhook URLs look like ``https://discord.com/api/webhooks/<id>/<token>``;
legacy hosts (discordapp.com, canary/ptb, /api/v10/ prefix) are accepted too.
Принимаем и устаревшие хосты (discordapp.com, canary/ptb, префикс /api/vN/).
"""

from __future__ import annotations

import re

_WEBHOOK_RE = re.compile(
    r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/(\d{17,22})/([\w.-]{20,})/?$"
)


def parse_webhook_url(url: str) -> tuple[str, str] | None:
    """Return ``(webhook_id, token)`` or ``None`` if the URL is not a webhook.
    Вернуть ``(webhook_id, token)`` либо ``None``, если URL не вебхука."""
    match = _WEBHOOK_RE.match(url.strip())
    return (match.group(1), match.group(2)) if match else None


def is_webhook_url(url: str) -> bool:
    return parse_webhook_url(url) is not None
