"""Module 5 tests: album creation (mocked webhook), link parsing, file naming.
Модуль 5: создание альбомов (замоканный вебхук), разбор ссылок, имена файлов."""

from __future__ import annotations

import pytest

from app.albums import (
    AlbumError, AlbumsService, ThreadImport, album_starter_content,
    format_shot_filename, parse_thread_link,
)
from app.discord_client import SendResult, WebhookDeadError
from app.models import WebhookProfile
from app.store import ConfigStore


class FakeClient:
    def __init__(self, channel_id="555555555555555555", fail: Exception | None = None) -> None:
        self.channel_id = channel_id
        self.fail = fail
        self.calls: list[dict] = []
        self.closed = False

    def execute(self, **kwargs) -> SendResult:
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        return SendResult(ok=True, message_id="1", channel_id=self.channel_id, guild_id="700000000000000001")

    def close(self) -> None:
        self.closed = True


def make_service(tmp_path, client: FakeClient):
    store = ConfigStore(tmp_path / "config.json")
    factory = lambda _profile: client  # noqa: E731
    return store, AlbumsService(store, client_factory=factory)


def forum_profile(store: ConfigStore) -> WebhookProfile:
    return store.add_profile("Форум", "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
                             channel_type="forum")


def test_parse_thread_link_variants() -> None:
    two = parse_thread_link("https://discord.com/channels/111111111111111111/222222222222222222")
    assert two and two.thread_id == "222222222222222222"
    three = parse_thread_link("https://canary.discord.com/channels/111111111111111111/222222222222222222/333333333333333333?query=1")
    assert three and (three.thread_id, three.message_id) == ("222222222222222222", "333333333333333333")
    raw = parse_thread_link("222222222222222222")
    assert raw and raw.thread_id == "222222222222222222"
    assert parse_thread_link("https://discord.com/channels/@me/222222222222222222") is None
    assert parse_thread_link("not a link") is None


def test_starter_content_card() -> None:
    card = album_starter_content("Дом #1644")
    assert "Дом #1644" in card and "Screensaver" in card


def test_create_album_registers_thread_id(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    album = service.create_album(profile, "Дом #1644, Каналы Веспуччи (Suvorov)")
    assert album.thread_id == "555555555555555555"
    assert album.name.startswith("Дом #1644")
    assert client.calls[0]["thread_name"] == "Дом #1644, Каналы Веспуччи (Suvorov)"
    assert "🖼" in client.calls[0]["content"]
    assert client.closed is True
    # persisted
    assert ConfigStore(tmp_path / "config.json").albums[0].thread_id == "555555555555555555"


def test_create_album_text_profile_rejected(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = store.add_profile(
        "Текст", "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        channel_type="text")
    with pytest.raises(AlbumError) as excinfo:
        service.create_album(profile, "Альбом")
    assert excinfo.value.code == "text_profile"
    assert client.calls == []


def test_create_album_validates_name(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    with pytest.raises(AlbumError) as excinfo:
        service.create_album(profile, "   ")
    assert excinfo.value.code == "empty_name"
    with pytest.raises(AlbumError):
        service.create_album(profile, "x" * 101)


def test_create_album_propagates_webhook_death(tmp_path) -> None:
    client = FakeClient(fail=WebhookDeadError("gone"))
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    with pytest.raises(WebhookDeadError):
        service.create_album(profile, "Альбом")
    assert store.albums == []  # nothing registered on failure


def test_attach_by_link(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    album = service.attach_by_link(profile, "https://discord.com/channels/111111111111111111/222222222222222222/333333333333333333",
                                   name="Существующая тема")
    assert album.thread_id == "222222222222222222"
    with pytest.raises(AlbumError):
        service.attach_by_link(profile, "https://example.com/nope")


def test_format_shot_filename() -> None:
    assert format_shot_filename("Гостевая спальня", 3, "png") == "Гостевая спальня | 3.png"
    assert format_shot_filename("Коридор: 2-й этаж", 12, "JPEG") == "Коридор_ 2-й этаж | 12.jpeg"
    assert format_shot_filename("  ", 1, ".webp") == "album | 1.webp"


def test_next_filenames_preview_does_not_consume_counter(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    album = store.add_album(profile.id, "Дом", "222222222222222222222222")
    album.last_number = 7
    store.save()
    first = service.next_filenames(album, "Спальня", "png", 3)
    assert first == ["Спальня | 8.png", "Спальня | 9.png", "Спальня | 10.png"]
    album = store.get_album(album.id)
    assert service.next_filenames(album, "Спальня", "png", 3) == first  # preview only
    assert store.get_album(album.id).last_number == 7


def test_rename_and_forget(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    album = store.add_album(profile.id, "Старое", "222222222222222222222222")
    renamed = service.rename_local(album.id, "Новое")
    assert renamed.name == "Новое"
    service.forget(album.id)
    assert store.albums == []
    with pytest.raises(AlbumError):
        service.rename_local(album.id, "Ещё раз")


def test_import_threads_registers_and_skips_duplicates(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    service.attach_by_link(profile, "222222222222222222", name="Уже есть")
    items = [
        ThreadImport(thread_id="222222222222222222", name="Уже есть"),   # duplicate → skipped
        ThreadImport(thread_id="333333333333333333", name="Кухня", last_number=16,
                     guild_id="700000000000000001"),
        ThreadImport(thread_id="", name="Битая запись"),                  # no id → skipped
    ]
    created, skipped = service.import_threads(profile, items)
    assert [a.thread_id for a in created] == ["333333333333333333"]
    assert skipped == 2
    album = created[0]
    assert album.guild_id == "700000000000000001"
    assert album.next_number == 17
    # duplicates don't multiply on a second pass
    again, again_skipped = service.import_threads(profile, items[:2])
    assert again == [] and again_skipped == 2


def test_import_threads_accepts_unknown_count(tmp_path) -> None:
    client = FakeClient()
    store, service = make_service(tmp_path, client)
    profile = forum_profile(store)
    created, skipped = service.import_threads(profile, [ThreadImport(thread_id="444444444444444444", name="Без номера")])
    assert len(created) == 1 and skipped == 0
    assert created[0].next_number == 1
