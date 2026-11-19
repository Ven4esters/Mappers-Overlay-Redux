"""Album service: create/link/rename/forget forum-post albums. / Сервис альбомов.

An "album" is a Discord forum post (thread) used as a screenshot collection.
Creating an album works through the webhook itself: the starter message carries
``thread_name`` and Discord spins up the post; its thread id arrives as the
message's ``channel_id`` (``?wait=true``).
«Альбом» — это тема-пост форума Discord. Создание идёт через сам вебхук:
стартовое сообщение несёт ``thread_name``, Discord создаёт пост, а id темы
приходит в ``channel_id`` ответа.

Listing threads is impossible through a webhook — the local registry plus
paste-a-link import is the API-compliant path.
Перечислять темы через вебхук нельзя — локальный реестр и импорт по ссылкам
это API-соблюдающий путь.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from app.discord_client import DiscordClient
from app.models import Album, WebhookProfile
from app.store import ConfigStore
from app.webhook_url import parse_webhook_url

THREAD_LINK_RE = re.compile(
    r"^(?:https?://)?(?:canary\.|ptb\.)?discord\.com/channels/(\d{17,22})/(\d{17,22})(?:/(\d{17,22}))?"
)
SNOWFLAKE_RE = re.compile(r"^\d{17,22}$")
MAX_THREAD_NAME = 100
STARTER_NAME_RE = re.compile(r"Альбом \«(.+?)\»")


class AlbumError(RuntimeError):
    """Album-flow failure with a machine code. / Ошибка сценария альбома."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ThreadImport:
    """An existing forum post to register locally. / Существующая публикация для регистрации."""

    thread_id: str
    name: str
    last_number: int = 0   # 0 → counter untouched (next shot = 1) / 0 — счётчик с нуля
    guild_id: str = ""


@dataclass(frozen=True)
class ThreadRef:
    """Parsed thread reference. / Разобранная ссылка на тему."""

    thread_id: str
    guild_id: str = ""
    message_id: str = ""


def parse_thread_link(text: str) -> Optional[ThreadRef]:
    """Parse a Discord jump link or a raw snowflake into a ThreadRef.
    Разобрать jump-ссылку Discord или «голый» snowflake в ThreadRef.

    Accepted / Принимаем:
      https://discord.com/channels/<guild>/<thread>
      https://discord.com/channels/<guild>/<thread>/<message>
      <thread snowflake>
    Note: for messages outside any thread the middle id is a plain channel — the
    same call posts fine there, so accepting it is deliberate.
    Для сообщений вне темы средний id — сам канал; постить туда тоже можно,
    поэтому принимаем намеренно.
    """
    text = text.strip()
    match = THREAD_LINK_RE.match(text)
    if match:
        guild_id, middle, message_id = match.groups()
        return ThreadRef(thread_id=middle, guild_id=guild_id, message_id=message_id or "")
    if SNOWFLAKE_RE.fullmatch(text):
        return ThreadRef(thread_id=text)
    return None


def parse_starter_name(content: str) -> str:
    """Extract the album name from a starter card this app created.
    Вычленить имя альбома из стартовой карточки, созданной приложением.

    Returns "" when the content is not a recognizable starter card.
    """
    match = STARTER_NAME_RE.search(content or "")
    return match.group(1).strip() if match else ""


def parse_import_lines(text: str) -> tuple[list["ThreadRef"], list[str]]:
    """Parse pasted lines (jump links / bare IDs), de-duplicated by thread.
    Разобрать вставленные строки (jump-ссылки / голые ID), без дублей тем.

    Returns (valid refs, invalid raw lines). / (валидные ссылки, битые строки)."""
    refs: list[ThreadRef] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        ref = parse_thread_link(line)
        if ref is None:
            invalid.append(line)
            continue
        if ref.thread_id in seen:
            continue
        seen.add(ref.thread_id)
        refs.append(ref)
    return refs, invalid


def album_starter_content(name: str) -> str:
    """Starter card posted as the first message of a fresh album. / Карточка альбома."""
    return f"🖼️  Альбом «{name.strip()}»\nсоздан через Screensaver → Discord"[:2000]


def format_shot_filename(section: str, number: int, ext: str = "png") -> str:
    """«Название секции | N.ext» — the upload display name. / Имя файла для загрузки."""
    from app.discord_client import sanitize_filename

    ext = ext.lstrip(".").lower() or "png"
    clean_section = sanitize_filename(section, fallback="album").strip(" .") or "album"
    return f"{clean_section[:200]} | {int(number)}.{ext}"


class AlbumsService:
    """Album operations on top of the store + webhook client. / Операции над альбомами."""

    def __init__(self, store: ConfigStore,
                 client_factory: Optional[Callable[[WebhookProfile], DiscordClient]] = None) -> None:
        self.store = store
        self._client_factory = client_factory or self._default_client_factory

    @staticmethod
    def _default_client_factory(profile: WebhookProfile) -> DiscordClient:
        if parse_webhook_url(profile.webhook_url) is None:
            raise AlbumError("invalid_webhook", "Profile does not hold a valid webhook URL / В профиле невалидный URL")
        return DiscordClient(profile.webhook_url)

    # -------------------------------------------------------------- create
    def create_album(self, profile: WebhookProfile, name: str) -> Album:
        """Create an empty album (forum post) and register it locally.
        Создать пустой альбом (пост форума) и зарегистрировать локально."""
        name = name.strip()
        if not name:
            raise AlbumError("empty_name", "Album name is required / Название альбома обязательно")
        if len(name) > MAX_THREAD_NAME:
            raise AlbumError("name_too_long", f"Album name exceeds {MAX_THREAD_NAME} chars / Название слишком длинное")
        if not profile.is_forum:
            raise AlbumError(
                "text_profile",
                "Albums can be created only in forum channels — for text channels add an existing thread by link / "
                "Альбомы создаются только в форуме; для текстового канала добавьте тему по ссылке")

        client = self._client_factory(profile)
        try:
            result = client.execute(content=album_starter_content(name), thread_name=name,
                                    username=profile.username_override or None,
                                    avatar_url=profile.avatar_url or None)
        finally:
            client.close()
        if not result.channel_id:
            raise AlbumError("no_thread_id", "Discord did not return the new thread id / Discord не вернул id темы")
        album = self.store.add_album(profile.id, name, result.channel_id)
        if result.guild_id:
            self.store.update_album(album.id, guild_id=result.guild_id)
        self.store.touch_profile(profile.id)
        return album

    # ------------------------------------------------------------- import
    def import_threads(self, profile: WebhookProfile, items: list[ThreadImport]) -> tuple[list[Album], int]:
        """Register existing forum posts as albums; skips ones already in the registry.
        Привязать существующие публикации как альбомы; дубликаты пропускаются.

        Returns (created albums, skipped duplicates). / (созданные, пропущенные)."""
        known = {a.thread_id for a in self.store.albums_for(profile.id)}
        created: list[Album] = []
        skipped = 0
        for item in items:
            thread_id = (item.thread_id or "").strip()
            if not thread_id or thread_id in known:
                skipped += 1
                continue
            name = (item.name or "").strip()[:MAX_THREAD_NAME] or f"Thread {thread_id}"
            album = self.store.add_album(profile.id, name, thread_id)
            changes: dict[str, object] = {}
            if item.guild_id:
                changes["guild_id"] = item.guild_id
            if item.last_number > 0:
                changes["last_number"] = int(item.last_number)
            if changes:
                self.store.update_album(album.id, **changes)
            known.add(thread_id)
            created.append(album)
        return created, skipped

    # --------------------------------------------------------------- link
    def attach_by_link(self, profile: WebhookProfile, link: str, name: str = "") -> Album:
        """Register an existing thread as an album. / Привязать существующую тему как альбом."""
        ref = parse_thread_link(link)
        if ref is None:
            raise AlbumError("bad_link", "Not a Discord thread link or snowflake / Не похоже на ссылку на тему")
        display = name.strip() or f"Thread {ref.thread_id}"
        album = self.store.add_album(profile.id, display, ref.thread_id)
        if ref.guild_id:
            self.store.update_album(album.id, guild_id=ref.guild_id)
        return album

    # --------------------------------------------------------------- misc
    def rename_local(self, album_id: str, name: str) -> Album:
        name = name.strip()
        if not name:
            raise AlbumError("empty_name", "Album name is required / Название альбома обязательно")
        album = self.store.update_album(album_id, name=name)
        if album is None:
            raise AlbumError("not_found", "Album not found / Альбом не найден")
        return album

    def forget(self, album_id: str) -> None:
        """Drop the album from the local registry (Discord untouched). / Забыть локально."""
        self.store.remove_album(album_id)

    def next_filenames(self, album: Album, section: str, ext: str, count: int) -> list[str]:
        """Preview the next ``count`` names without consuming the counter.
        Подсмотреть следующие ``count`` имён, не тратя счётчик."""
        if count < 1:
            return []
        start = album.next_number
        return [format_shot_filename(section, start + i, ext) for i in range(count)]
