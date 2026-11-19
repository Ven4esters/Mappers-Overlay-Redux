"""Domain models for config and history. / Доменные модели конфигурации и истории.

All models are plain dataclasses with ``to_dict``/``from_dict`` so the store
layer can persist them without ORMs or code generation. Unknown JSON keys are
ignored on read (forward compatibility).
Все модели — простые dataclasses с to_dict/from_dict; неизвестные ключи JSON
игнорируются (прямая совместимость).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow_iso() -> str:
    """UTC timestamp in ISO-8601 (second precision). / Метка времени UTC."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def _pick(raw: dict, key: str, default):
    value = raw.get(key, default)
    return default if value is None else value


# ---------------------------------------------------------------- settings
@dataclass
class AppSettings:
    """User-tunable settings. / Настройки пользователя."""

    language: str = "ru"  # ru | en
    send_mode: str = "ask"  # ask | single | separate
    duplicate_caption: bool = False  # reuse caption in every message (separate mode)
    section_style: str = "text"  # text | embed
    keep_local_cache: bool = True
    bb_media_tag: str = "IMG"  # IMG | MEDIA | CUSTOM
    bb_custom_media_tag: str = ""  # used when bb_media_tag == "CUSTOM", e.g. "MEDIA type=\"imgur\""
    bb_heading_template: str = "[B][SIZE=6][COLOR=#FFD34D]{title}[/COLOR][/SIZE][/B]"
    clear_fields_after_send: bool = True
    active_profile_id: str = ""
    use_keyring: bool = False
    last_capture_mode: str = "fullscreen"  # fullscreen | window | region (PrintScreen overlay)
    capture_hotkey: str = "Print"          # global hotkey for the capture overlay (e.g. "Print", "F9")
    minimize_to_tray: bool = False           # close-to-tray instead of quitting

    @classmethod
    def from_dict(cls, raw: dict) -> "AppSettings":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in raw.items() if k in known}
        return cls(**clean)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# ---------------------------------------------------------------- profiles
@dataclass
class WebhookProfile:
    """A Discord webhook endpoint with display metadata. / Профиль вебхука."""

    id: str
    name: str
    webhook_url: str
    channel_type: str = "forum"  # forum | text
    username_override: str = ""
    avatar_url: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    last_used_at: str = ""

    @property
    def is_forum(self) -> bool:
        return self.channel_type == "forum"

    @classmethod
    def from_dict(cls, raw: dict) -> "WebhookProfile":
        return cls(
            id=_pick(raw, "id", new_id()),
            name=str(_pick(raw, "name", "Webhook")),
            webhook_url=str(_pick(raw, "webhook_url", "")),
            channel_type=str(_pick(raw, "channel_type", "forum")) or "forum",
            username_override=str(_pick(raw, "username_override", "")),
            avatar_url=str(_pick(raw, "avatar_url", "")),
            created_at=str(_pick(raw, "created_at", utcnow_iso())),
            last_used_at=str(_pick(raw, "last_used_at", "")),
        )

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# ------------------------------------------------------------------ albums
@dataclass
class Album:
    """A Discord forum post (thread) used as a screenshot "album". / Альбом-тема."""

    id: str
    profile_id: str
    name: str
    thread_id: str
    guild_id: str = ""  # captured when known (create/attach) — powers “Open in Discord”
    created_at: str = field(default_factory=utcnow_iso)
    last_sent_at: str = ""
    messages_sent: int = 0
    shots_sent: int = 0
    last_number: int = 0

    @property
    def next_number(self) -> int:
        return self.last_number + 1

    def register_send(self, shots: int, messages: int = 1) -> None:
        """Account a successful send. / Учесть успешную отправку."""
        self.last_number += max(0, shots)
        self.shots_sent += max(0, shots)
        self.messages_sent += max(0, messages)
        self.last_sent_at = utcnow_iso()

    @classmethod
    def from_dict(cls, raw: dict) -> "Album":
        return cls(
            id=_pick(raw, "id", new_id()),
            profile_id=str(_pick(raw, "profile_id", "")),
            name=str(_pick(raw, "name", "Album")),
            thread_id=str(_pick(raw, "thread_id", "")),
            guild_id=str(_pick(raw, "guild_id", "")),
            created_at=str(_pick(raw, "created_at", utcnow_iso())),
            last_sent_at=str(_pick(raw, "last_sent_at", "")),
            messages_sent=int(_pick(raw, "messages_sent", 0) or 0),
            shots_sent=int(_pick(raw, "shots_sent", 0) or 0),
            last_number=int(_pick(raw, "last_number", 0) or 0),
        )

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# ----------------------------------------------------------------- history
@dataclass
class Attachment:
    """One uploaded file. / Один загруженный файл."""

    filename: str
    url: str = ""
    local_path: str = ""
    catbox_url: str = ""  # permanent link from catbox.moe (set on BB-code export)

    @classmethod
    def from_dict(cls, raw: dict) -> "Attachment":
        return cls(
            filename=str(_pick(raw, "filename", "file.png")),
            url=str(_pick(raw, "url", "")),
            local_path=str(_pick(raw, "local_path", "")),
            catbox_url=str(_pick(raw, "catbox_url", "")),
        )

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class HistoryItem:
    """A sent (or failed) section of an album. / Отправленная (или упавшая) секция."""

    id: str
    album_id: str
    album_name: str
    section: str
    created_at: str = field(default_factory=utcnow_iso)
    description: str = ""
    message_url: str = ""
    status: str = "ok"  # ok | failed
    error: str = ""
    attachments: list[Attachment] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "HistoryItem":
        return cls(
            id=_pick(raw, "id", new_id()),
            album_id=str(_pick(raw, "album_id", "")),
            album_name=str(_pick(raw, "album_name", "")),
            section=str(_pick(raw, "section", "")),
            created_at=str(_pick(raw, "created_at", utcnow_iso())),
            description=str(_pick(raw, "description", "")),
            message_url=str(_pick(raw, "message_url", "")),
            status=str(_pick(raw, "status", "ok")),
            error=str(_pick(raw, "error", "")),
            attachments=[Attachment.from_dict(a) for a in _pick(raw, "attachments", [])],
        )

    def to_dict(self) -> dict:
        data = dict(self.__dict__)
        data["attachments"] = [a.to_dict() for a in self.attachments]
        return data
