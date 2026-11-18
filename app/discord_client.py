"""Discord webhook client — the heart of the app. / Клиент вебхуков Discord.

Synchronous by design: the UI runs it on a QThread. All retries, 429 handling,
error-code mapping and attachment bookkeeping live here so the UI stays simple.
Синхронный дизайн: UI держит вызовы в QThread. Ретраи, 429, маппинг кодов ошибок
и учёт вложений — здесь, чтобы UI оставался простым.

Key Discord facts (see README / Task docs):
- POST /api/webhooks/{id}/{token}, multipart/form-data, field ``payload_json``;
- forum channels REQUIRE ``thread_id`` (in query) or ``thread_name`` (in body);
- ≤10 files and ≤10 embeds per message; embed total ≤6000 chars; file ≤20 MiB;
- HTTP 429 carries ``retry_after`` (we honour it); 404 = webhook is gone.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

import httpx

MAX_FILES_PER_MESSAGE = 10
MAX_CONTENT_CHARS = 2000
MAX_EMBED_TITLE = 256
MAX_EMBED_DESCRIPTION = 4096
MAX_FILENAME = 255
EMBED_ACCENT = 0x4F7DFF
DEFAULT_TIMEOUT = 45.0
DEFAULT_MAX_ATTEMPTS = 3
INTER_MESSAGE_DELAY = 0.6


# --------------------------------------------------------------------- io
@dataclass
class UploadedFile:
    """A file ready for upload. / Готовый к загрузке файл."""

    filename: str
    data: bytes
    content_type: str = "image/png"


@dataclass
class SendResult:
    """One successfully executed webhook call. / Успешно выполненный вызов вебхука."""

    ok: bool
    message_id: str = ""
    channel_id: str = ""
    guild_id: str = ""
    message_url: str = ""
    attachments: list[dict] = field(default_factory=list)  # [{filename, url}]


@dataclass
class SectionInput:
    """One screenshot group: a caption + its files. / Одна секция: подпись + файлы."""

    name: str
    files: list[UploadedFile]
    description: str = ""


# ----------------------------------------------------------------- errors
class DiscordError(RuntimeError):
    """Base error with a machine-readable ``code``. / Базовая ошибка с кодом."""

    code = "unknown"


class WebhookDeadError(DiscordError):
    code = "webhook_dead"


class PayloadTooLargeError(DiscordError):
    code = "too_large"


class RateLimitedError(DiscordError):
    code = "rate_limited"

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ForumError(DiscordError):
    code = "forum"

    def __init__(self, message: str, api_code: int = 0) -> None:
        super().__init__(message)
        self.api_code = api_code


class ValidationFailedError(DiscordError):
    code = "validation"


class TransientDiscordError(DiscordError):
    code = "transient"


class SectionSendError(DiscordError):
    """Raised when part of a section could not be delivered. Carries partial progress.
    Секция не доставлена целиком. Несёт частичный прогресс (для UI и истории)."""

    code = "section_failed"

    def __init__(self, message: str, *, cause: DiscordError | None = None,
                 delivered: list[SendResult] | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        self.delivered = delivered or []


class SectionAborted(SectionSendError):
    """User cancelled between messages. / Отменено пользователем между сообщениями."""

    code = "aborted"


# ------------------------------------------------------------- primitives
_FORBIDDEN_FILENAME_CHARS = '\\/:*?"<>'


def sanitize_filename(name: str, *, keep_pipe: bool = True, fallback: str = "file.png") -> str:
    """Make a Discord-safe display filename. / Безопасное отображаемое имя файла.

    ``|`` is kept (uploads don't touch the disk; the UI shows this exact name),
    every other Windows-forbidden character is replaced with ``_``.
    ``fallback`` is used when nothing usable remains after cleaning.
    Символ «|» сохраняется; прочие запрещённые — «_»; ``fallback`` — на случай пустой строки.
    """
    cleaned = "".join("_" if ch in _FORBIDDEN_FILENAME_CHARS else ch for ch in name).strip()
    cleaned = " ".join(cleaned.split())  # collapse weird whitespace
    return (cleaned[:MAX_FILENAME] if cleaned else fallback)


def dedupe_filenames(files: list[UploadedFile]) -> list[UploadedFile]:
    """Avoid duplicate filenames inside one message. / Уникальные имена в одном сообщении."""
    seen: dict[str, int] = {}
    out: list[UploadedFile] = []
    for item in files:
        stem, dot, ext = item.filename.rpartition(".")
        count = seen.get(item.filename, 0)
        if count == 0:
            seen[item.filename] = 1
            out.append(item)
            continue
        suffix = f"-{count + 1}"
        new_name = f"{stem}{suffix}.{ext}" if dot else f"{item.filename}{suffix}"
        while new_name in seen:
            count += 1
            suffix = f"-{count + 1}"
            new_name = f"{stem}{suffix}.{ext}" if dot else f"{item.filename}{suffix}"
        seen[item.filename] = count + 1
        seen[new_name] = 1
        out.append(UploadedFile(new_name, item.data, item.content_type))
    return out


def chunk_files(files: list[UploadedFile], per_message: int = MAX_FILES_PER_MESSAGE) -> list[list[UploadedFile]]:
    """Split into per-message batches of at most ``per_message``. / Разбить на пакеты ≤10."""
    if per_message < 1:
        raise ValueError("per_message must be >= 1")
    return [files[i:i + per_message] for i in range(0, len(files), per_message)]


def build_content(name: str, description: str) -> str:
    """Plain-text caption: **Heading** + description line. / Текстовая подпись."""
    title = name.strip()
    desc = description.strip()
    if not title and desc:
        content = desc[:MAX_CONTENT_CHARS]
    elif title and desc:
        content = f"**{title}**\n{desc}"[:MAX_CONTENT_CHARS]
    else:
        content = f"**{title}**" if title else ""
    return content


def build_embed(name: str, description: str, image_filename: Optional[str] = None,
                color: int = EMBED_ACCENT) -> dict:
    """Embed caption; image references the attachment by name. / Embed-подпись."""
    title = name.strip()[:MAX_EMBED_TITLE]
    embed: dict = {"color": color}
    if title:
        embed["title"] = title
    desc = description.strip()
    if desc:
        embed["description"] = desc[:MAX_EMBED_DESCRIPTION]
    if image_filename:
        embed["image"] = {"url": f"attachment://{image_filename}"}
    return embed


# ------------------------------------------------------------------ client
class DiscordClient:
    def __init__(self, webhook_url: str, *, timeout: float = DEFAULT_TIMEOUT,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 inter_delay: float = INTER_MESSAGE_DELAY,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.webhook_url = webhook_url.strip()
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.inter_delay = max(0.0, inter_delay)
        self._sleep = sleeper
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------- single message
    def execute(self, *, content: Optional[str] = None, embeds: Optional[list[dict]] = None,
                files: Optional[list[UploadedFile]] = None,
                thread_id: Optional[str] = None, thread_name: Optional[str] = None,
                username: Optional[str] = None, avatar_url: Optional[str] = None) -> SendResult:
        """Execute the webhook with retries. / Выполнить вебхук с ретраями."""
        files = dedupe_filenames(files or [])
        payload: dict = {}
        if content:
            payload["content"] = content[:MAX_CONTENT_CHARS]
        if embeds:
            payload["embeds"] = embeds[:10]
        if thread_name:
            payload["thread_name"] = thread_name.strip()[:100]
        if username:
            payload["username"] = username.strip()[:80]
        if avatar_url:
            payload["avatar_url"] = avatar_url.strip()
        if not payload and not files:
            raise ValidationFailedError("Empty webhook call / Пустой вызов вебхука (нет текста и файлов)")

        params: dict[str, str] = {"wait": "true"}
        if thread_id:
            params["thread_id"] = thread_id.strip()

        data = {"payload_json": json.dumps(payload, ensure_ascii=False)}
        multipart = [("files[%d]" % i, (f.filename, f.data, f.content_type)) for i, f in enumerate(files)]

        last_retry_after = 0.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http.post(self.webhook_url, params=params, data=data,
                                           files=multipart or None)
            except httpx.HTTPError as exc:
                if attempt >= self.max_attempts:
                    raise TransientDiscordError(f"Network error / Сетевая ошибка: {exc}") from exc
                self._sleep(min(2 ** attempt, 5))
                continue

            code = response.status_code
            if code in (200, 201):
                return self._parse_message(response)
            if code == 204:
                return SendResult(ok=True)
            if code == 429:
                wait = self._retry_after(response)
                last_retry_after = wait
                if attempt >= self.max_attempts:
                    raise RateLimitedError(
                        f"Rate limited, retry after {wait:.1f}s / Превышен лимит запросов", retry_after=wait)
                self._sleep(min(max(wait, 0.5), 15.0))
                continue
            if 500 <= code < 600:
                if attempt >= self.max_attempts:
                    raise TransientDiscordError(f"Discord is unavailable (HTTP {code}) / Дискорд недоступен")
                self._sleep(min(2 ** attempt, 8))
                continue
            self._raise_for_client_error(response)
        raise RateLimitedError("Rate limited / Лимит запросов", retry_after=last_retry_after)

    # -------------------------------------------------------------- section
    def send_section(self, section: SectionInput, *, style: Literal["text", "embed"] = "text",
                     thread_id: Optional[str] = None, thread_name: Optional[str] = None,
                     username: Optional[str] = None, avatar_url: Optional[str] = None,
                     duplicate_caption: bool = False,
                     on_progress: Optional[Callable[[int, int], None]] = None,
                     should_abort: Optional[Callable[[], bool]] = None) -> list[SendResult]:
        """Send one album section (caption + images, split into ≤10-file messages).
        Отправить одну секцию альбома (подпись + изображения, пакеты по ≤10 файлов)."""
        name = section.name.strip()
        if not name:
            raise ValidationFailedError("Section name is required / Название секции обязательно")
        if not section.files:
            raise ValidationFailedError("Section has no files / В секции нет файлов")

        if thread_id:
            thread_name = None  # Discord rejects both at once (220002); thread_id wins
        chunks = chunk_files(dedupe_filenames(section.files))
        results: list[SendResult] = []
        created_thread_id: Optional[str] = None
        for index, chunk in enumerate(chunks):
            if should_abort and should_abort():
                raise SectionAborted(f"Aborted before message {index + 1}/{len(chunks)} / "
                                     f"Отменено перед сообщением {index + 1}/{len(chunks)}",
                                     delivered=results)
            caption_here = index == 0 or duplicate_caption
            if style == "embed":
                content = None
                embeds = [build_embed(name, section.description, chunk[0].filename)] if caption_here else None
            else:
                content = build_content(name, section.description) if caption_here else None
                embeds = None
            if index == 0:
                effective_thread_id, effective_thread_name = thread_id, thread_name
            elif thread_name:
                # The first chunk created the forum thread; post the rest into it.
                effective_thread_id, effective_thread_name = created_thread_id or thread_id, None
            else:
                effective_thread_id, effective_thread_name = thread_id, None
            try:
                results.append(self.execute(
                    content=content, embeds=embeds,
                    files=chunk, thread_id=effective_thread_id,
                    thread_name=effective_thread_name,
                    username=username, avatar_url=avatar_url,
                ))
            except DiscordError as exc:
                if results:  # some messages already delivered — report partial progress
                    raise SectionSendError(
                        f"Section '{name}' failed on message {index + 1}/{len(chunks)} / "
                        f"Секция «{name}» упала на сообщении {index + 1}/{len(chunks)}: {exc}",
                        cause=exc, delivered=results) from exc
                raise  # nothing delivered — keep the precise error for the caller
            if index == 0 and thread_name and results:
                created_thread_id = results[-1].channel_id or None
            if on_progress:
                on_progress(index + 1, len(chunks))
            if index < len(chunks) - 1 and self.inter_delay:
                self._sleep(self.inter_delay)
        return results

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        try:
            body = response.json()
        except ValueError:
            return 1.0
        try:
            return float(body.get("retry_after", 1.0))
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _parse_message(response: httpx.Response) -> SendResult:
        try:
            message = response.json()
        except ValueError:
            return SendResult(ok=True)
        channel_id = str(message.get("channel_id", ""))
        message_id = str(message.get("id", ""))
        guild_id = str(message.get("guild_id", ""))
        url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}" if guild_id and channel_id and message_id else ""
        attachments = [{"filename": a.get("filename", ""), "url": a.get("url", a.get("proxy_url", ""))}
                       for a in message.get("attachments", []) if isinstance(a, dict)]
        return SendResult(ok=True, message_id=message_id, channel_id=channel_id,
                          guild_id=guild_id, message_url=url, attachments=attachments)

    @staticmethod
    def _raise_for_client_error(response: httpx.Response) -> None:
        try:
            body = response.json()
            api_code = int(body.get("code", 0))
            api_message = str(body.get("message", response.text[:200]))
        except (ValueError, TypeError):
            api_code, api_message = 0, response.text[:200]

        if response.status_code == 404 or api_code in (10015, 10003):
            raise WebhookDeadError(f"Webhook is gone or channel is missing / Вебхук удалён или канал не найден ({api_code})")
        if response.status_code in (400, 413) and api_code == 40005:
            raise PayloadTooLargeError("File is too large (limit ≈20 MiB) / Файл слишком большой (≈20 МиБ)")
        if api_code in (220001, 220002, 220003):
            hint = {
                220001: "Forum webhook needs a thread: pick an album or create one / Форуму нужна тема: выберите альбом",
                220002: "Both thread_id and thread_name were sent — pick one / Переданы и thread_id, и thread_name",
                220003: "thread_name works only in forum/media channels / thread_name работает только в форумах",
            }.get(api_code, "Forum error / Ошибка форума")
            raise ForumError(f"{hint} (code {api_code})", api_code=api_code)
        raise ValidationFailedError(f"Discord rejected the payload (HTTP {response.status_code}, code {api_code}): {api_message}")
