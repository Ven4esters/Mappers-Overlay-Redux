"""Forum discovery: list existing forum posts («альбомы-публикации»).
Поиск существующих публикаций на форуме.

A webhook cannot list threads, so discovery needs a bot token with VIEW_CHANNEL
(READ_MESSAGE_HISTORY only for the optional «следующий номер» sniff). The token
is used for the duration of the operation and is never persisted.
Вебхук не умеет перечислять темы — нужен бот с VIEW_CHANNEL (READ_MESSAGE_HISTORY
нужен только для опционального определения следующего номера). Токен живёт ровно
на время операции и нигде не сохраняется.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

API_BASE = "https://discord.com/api/v10"
SNOWFLAKE_RE = re.compile(r"^\d{17,22}$")
_SHOT_NUMBER_RE = re.compile(r"\|\s*(\d+)\s*\.[A-Za-z0-9]{1,5}$")
FORUM_CHANNEL_TYPES = {15, 16}  # GUILD_FORUM = 15, GUILD_MEDIA = 16
DEFAULT_TIMEOUT = 15.0


class ForumDiscoveryError(RuntimeError):
    """Discovery failure with a machine code. / Ошибка поиска с кодом."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass
class ThreadCandidate:
    """One forum post returned by the Discord REST API. / Пост форума из REST API."""

    thread_id: str
    name: str
    archived: bool
    message_count: int | None = None
    created_timestamp: str = ""  # snowflake sort falls back to this


@dataclass
class ChannelInfo:
    """Minimal channel identity. / Минимум о канале."""

    channel_id: str
    name: str
    guild_id: str = ""
    type: int = 0

    @property
    def is_forum(self) -> bool:
        return self.type in FORUM_CHANNEL_TYPES


def _headers(bot_token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {bot_token.strip()}", "Accept": "application/json"}


def _validate_snowflake(value: str, what: str) -> str:
    value = value.strip()
    if not SNOWFLAKE_RE.fullmatch(value):
        raise ForumDiscoveryError("bad_id", f"{what} must be a 17–22 digit Discord ID / {what} — числовой ID Discord")
    return value


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise ForumDiscoveryError("transient", f"Network error / Сетевая ошибка: {exc}") from exc
    _check(response)
    return response


def _check(response: httpx.Response) -> None:
    code = response.status_code
    if code in (200, 201):
        return
    if code == 401:
        raise ForumDiscoveryError("auth", "Invalid bot token / Неверный токен бота")
    if code == 403:
        raise ForumDiscoveryError("forbidden", "Bot cannot view this channel / Бот не видит этот канал")
    if code == 404:
        raise ForumDiscoveryError("not_found", "Channel not found — bot not in the guild, or wrong ID / Канал не найден (бот не на сервере или неверный ID)")
    if code == 429:
        raise ForumDiscoveryError("rate_limited", "Rate limited — retry later / Превышен лимит запросов")
    detail = ""
    try:
        body = response.json()
        detail = str(body.get("message") or body.get("code") or "")
    except ValueError:
        detail = (response.text or "")[:200]
    raise ForumDiscoveryError("http", f"HTTP {code}: {detail}")


def _threads_from(payload: object, *, archived: bool) -> list[ThreadCandidate]:
    if not isinstance(payload, dict):
        return []
    raw_threads = payload.get("threads")
    if not isinstance(raw_threads, list):
        return []
    result: list[ThreadCandidate] = []
    for obj in raw_threads:
        if not isinstance(obj, dict):
            continue
        thread_id = str(obj.get("id", "") or "")
        name = str(obj.get("name", "") or "")[:100]
        if not thread_id:
            continue
        meta = obj.get("thread_metadata") if isinstance(obj.get("thread_metadata"), dict) else {}
        created = str(meta.get("create_timestamp", "") or "")
        raw_count = obj.get("message_count")
        message_count = int(raw_count) if isinstance(raw_count, int) or (isinstance(raw_count, str) and raw_count.isdigit()) else None
        result.append(ThreadCandidate(thread_id=thread_id, name=name, archived=archived,
                                      message_count=message_count, created_timestamp=created))
    return result


def get_channel_info(bot_token: str, channel_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> ChannelInfo:
    """Fetch the channel (validates token + membership). / Узнать канал."""
    channel_id = _validate_snowflake(channel_id, "channel_id")
    with httpx.Client(headers=_headers(bot_token), timeout=timeout) as client:
        info = _request(client, "GET", f"{API_BASE}/channels/{channel_id}").json()
    if not isinstance(info, dict):
        raise ForumDiscoveryError("http", "Bad channel payload / Некорректный ответ о канале")
    return ChannelInfo(channel_id=channel_id, name=str(info.get("name") or ""),
                       guild_id=str(info.get("guild_id") or ""),
                       type=int(info.get("type") if isinstance(info.get("type"), int) else 0))


def list_forum_threads(bot_token: str, channel_id: str, *, limit: int = 100,
                       timeout: float = DEFAULT_TIMEOUT) -> list[ThreadCandidate]:
    """List active + archived public threads of a forum channel, newest first.
    Список активных и публичных архивных тем форума, новые сверху."""
    channel_id = _validate_snowflake(channel_id, "channel_id")
    limit = max(1, min(int(limit), 100))
    base = f"{API_BASE}/channels/{channel_id}"
    with httpx.Client(headers=_headers(bot_token), timeout=timeout) as client:
        active = _threads_from(_request(client, "GET", f"{base}/threads/active").json(),
                               archived=False)
        archived = _threads_from(
            _request(client, "GET", f"{base}/threads/archived/public",
                     params={"limit": str(limit)}).json(),
            archived=True)
    seen: set[str] = set()
    merged: list[ThreadCandidate] = []
    for cand in (*active, *archived):
        if cand.thread_id not in seen:
            seen.add(cand.thread_id)
            merged.append(cand)
    merged.sort(key=lambda t: (t.created_timestamp, t.thread_id), reverse=True)
    return merged


def guess_last_number(filenames: list[str]) -> int:
    """Infer «Название | N.ext» counters; returns next free number (1 when none found).
    Определить следующий номер из имён «Название | N.ext»."""
    last = 0
    for filename in filenames:
        match = _SHOT_NUMBER_RE.search(str(filename))
        if match:
            try:
                last = max(last, int(match.group(1)))
            except ValueError:
                continue
    return last + 1


def fetch_thread_next_number(bot_token: str, thread_id: str, *, limit: int = 20,
                             timeout: float = DEFAULT_TIMEOUT) -> int:
    """Sniff the last «… | N.ext» in recent thread messages. Best effort: falls back to 1.
    Определить следующий номер по последним сообщениям темы. Best effort → 1."""
    thread_id = _validate_snowflake(thread_id, "thread_id")
    limit = max(1, min(int(limit), 100))
    try:
        with httpx.Client(headers=_headers(bot_token), timeout=timeout) as client:
            payload = _request(client, "GET", f"{API_BASE}/channels/{thread_id}/messages",
                               params={"limit": str(limit)}).json()
    except ForumDiscoveryError:
        return 1  # history sniffing is optional; never fail the whole import for it
    filenames: list[str] = []
    if isinstance(payload, list):
        for message in payload:
            if not isinstance(message, dict):
                continue
            for attachment in message.get("attachments") or []:
                if isinstance(attachment, dict):
                    name = attachment.get("filename")
                    if name:
                        filenames.append(str(name))
    return guess_last_number(filenames)
