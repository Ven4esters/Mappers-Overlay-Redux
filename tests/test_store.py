"""Module 2 tests: models, store roundtrip, corrupt-file recovery, webhook URL.
Модуль 2: модели, хранилище, восстановление после повреждения, URL вебхука."""

from __future__ import annotations

import json

import pytest

from app.models import Album, AppSettings, HistoryItem, utcnow_iso
from app.store import ConfigStore, HistoryStore
from app.webhook_url import is_webhook_url, parse_webhook_url

VALID_URL = "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def make_store(tmp_path):
    return ConfigStore(tmp_path / "config.json"), tmp_path / "config.json"


def test_webhook_url_validation() -> None:
    assert is_webhook_url(VALID_URL)
    assert is_webhook_url("https://canary.discord.com/api/v10/webhooks/123456789012345678/AbCd-Ef_GhIjKlMnOpQrStUvWxYz0123456789/")
    assert is_webhook_url("https://discordapp.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789")
    assert not is_webhook_url("https://discord.com/api/webhooks/abc/token")
    assert not is_webhook_url("https://evil.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789")
    assert not is_webhook_url("")


def test_parse_webhook_url_groups() -> None:
    parsed = parse_webhook_url(VALID_URL)
    assert parsed == ("123456789012345678", "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789")


def test_profile_roundtrip(tmp_path) -> None:
    store, path = make_store(tmp_path)
    profile = store.add_profile(" Дом #1644 ", VALID_URL, channel_type="forum",
                                username_override="Clunimos | (Айдар)")
    assert profile.id and path.exists()

    store2, _ = make_store(tmp_path)
    loaded = store2.get_profile(profile.id)
    assert loaded is not None
    assert loaded.name == "Дом #1644"
    assert loaded.webhook_url == VALID_URL
    assert loaded.channel_type == "forum"
    assert loaded.username_override == "Clunimos | (Айдар)"
    assert store2.active_profile().id == profile.id


def test_add_profile_rejects_bad_url(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.add_profile("bad", "https://discord.com/channels/1/2")


def test_remove_profile_cascades_albums_keeps_active(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    p = store.add_profile("A", VALID_URL)
    store.add_album(p.id, "Альбом 1", "111111111111111111")
    store.remove_profile(p.id)
    assert store.profiles == []
    assert store.albums == []
    assert store.settings.active_profile_id == ""


def test_album_counter_and_register_send(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    p = store.add_profile("A", VALID_URL)
    album = store.add_album(p.id, "Дом #1644", "222222222222222222")
    assert album.next_number == 1
    album.register_send(shots=2)
    store.save()

    store2, _ = make_store(tmp_path)
    loaded = store2.get_album(album.id)
    assert loaded.last_number == 2
    assert loaded.shots_sent == 2
    assert loaded.messages_sent == 1
    assert loaded.next_number == 3
    assert loaded.last_sent_at


def test_album_export_import_merge(tmp_path) -> None:
    store, _ = make_store(tmp_path)
    p = store.add_profile("A", VALID_URL)
    store.add_album(p.id, "Дом #1644", "333333333333333333")

    export_file = tmp_path / "albums.json"
    assert store.export_albums(export_file) == 1

    # importing the same file again must skip duplicates
    added, skipped = store.import_albums(export_file)
    assert (added, skipped) == (0, 1)

    # wipe albums, re-import from the export
    store.albums = []
    added, skipped = store.import_albums(export_file)
    assert (added, skipped) == (1, 0)
    assert store.albums[0].thread_id == "333333333333333333"


def test_corrupt_config_recovers_with_backup(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ not json !", encoding="utf-8")
    store = ConfigStore(path)
    assert store.profiles == [] and store.settings.language == "ru"
    backups = list(tmp_path.glob("config.json.bak-*"))
    assert backups, "expected a backup of the corrupt file"


def test_settings_ignore_unknown_keys() -> None:
    settings = AppSettings.from_dict({"language": "en", "unknown_future_key": 123, "send_mode": "single"})
    assert settings.language == "en"
    assert settings.send_mode == "single"
    assert "unknown_future_key" not in settings.to_dict()


def test_history_append_and_clear(tmp_path) -> None:
    hist = HistoryStore(tmp_path / "history.json")
    hist.append(HistoryItem(id="1", album_id="a", album_name="Дом", section="Спальня"))
    hist.append(HistoryItem(id="2", album_id="a", album_name="Дом", section="Коридор",
                            status="failed", error="429"))
    items = hist.all()
    assert [i.id for i in items] == ["1", "2"]
    assert items[1].status == "failed"
    hist.clear()
    assert hist.all() == []


def test_history_item_roundtrip(tmp_path) -> None:
    hist = HistoryStore(tmp_path / "history.json")
    item = HistoryItem(
        id="x", album_id="a", album_name="Дом", section="Спальня",
        message_url="https://discord.com/channels/1/2/3",
        created_at=utcnow_iso(),
    )
    item.attachments = []
    hist.append(item)
    loaded = hist.all()[0]
    assert loaded.to_dict() == item.to_dict()
