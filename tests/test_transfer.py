"""Module 7 tests: export/import bundles + get_webhook_info. / Модуль 7: бэкап и проверка вебхука."""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

from app import transfer
from app.discord_client import DiscordClient, TransientDiscordError, WebhookDeadError
from app.transfer import TransferError, export_bundle, import_bundle

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
HOST_RE = re.compile(r"https://discord\.com/api/webhooks/\d+/[^/?]+.*")
NO_SLEEP = lambda _s: None  # noqa: E731


def seed_state(tmp_path) -> tuple:
    config = tmp_path / "config.json"
    history = tmp_path / "history.json"
    config.write_text(json.dumps({
        "version": 1,
        "settings": {"language": "ru", "send_mode": "ask"},
        "profiles": [{"id": "p1", "name": "Дом", "webhook_url": WEBHOOK, "channel_type": "forum"}],
        "albums": [{"id": "a1", "profile_id": "p1", "name": "Альбом", "thread_id": "111"}],
    }), encoding="utf-8")
    history.write_text(json.dumps({
        "version": 1,
        "items": [{"id": "h1", "album_id": "a1", "section": "Спальня", "status": "ok"}],
    }), encoding="utf-8")
    return config, history


def test_export_import_roundtrip(tmp_path) -> None:
    config, history = seed_state(tmp_path)
    dest = tmp_path / "bundle.json"
    export_bundle(dest, config_path=config, history_path=history)

    exported = json.loads(dest.read_text(encoding="utf-8"))
    assert exported["bundle_version"] == transfer.BUNDLE_VERSION
    assert exported["config"]["profiles"][0]["id"] == "p1"
    assert exported["history"]["items"][0]["id"] == "h1"

    # wipe state, then import — files must be identical to the seeded ones
    seeded_config = config.read_text(encoding="utf-8")
    seeded_history = history.read_text(encoding="utf-8")
    config.write_text('{"version": 1}', encoding="utf-8")
    history.write_text('{"version": 1, "items": []}', encoding="utf-8")

    result = import_bundle(dest, config_path=config, history_path=history,
                           backup_root=tmp_path / "backups")
    assert json.loads(config.read_text(encoding="utf-8"))["profiles"][0]["id"] == "p1"
    assert json.loads(history.read_text(encoding="utf-8"))["items"][0]["id"] == "h1"
    # backup captured the wiped (pre-import) files
    assert (result.backup_dir / "config.json").exists()
    assert json.loads((result.backup_dir / "config.json").read_text(encoding="utf-8")) == {"version": 1}
    assert seeded_config != '{"version": 1}'
    assert seeded_history  # non-empty seed


def test_import_rejects_garbage(tmp_path) -> None:
    config, history = seed_state(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    with pytest.raises(TransferError):
        import_bundle(bad, config_path=config, history_path=history,
                      backup_root=tmp_path / "backups")

    bad.write_text('{"config": {"unrelated": true}}', encoding="utf-8")
    with pytest.raises(TransferError):
        import_bundle(bad, config_path=config, history_path=history,
                      backup_root=tmp_path / "backups")

    # nothing was overwritten
    assert json.loads(config.read_text(encoding="utf-8"))["profiles"][0]["id"] == "p1"


def test_import_rejects_corrupt_history(tmp_path) -> None:
    config, history = seed_state(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"config": {"profiles": []}, "history": "oops"}), encoding="utf-8")
    with pytest.raises(TransferError):
        import_bundle(bad, config_path=config, history_path=history,
                      backup_root=tmp_path / "backups")


@respx.mock
def test_get_webhook_info_ok() -> None:
    respx.get(url__regex=HOST_RE).mock(return_value=httpx.Response(200, json={
        "id": "123456789012345678", "name": "album-bot", "channel_id": "800000000000000009",
        "guild_id": "700000000000000009", "type": 1,
    }))
    client = DiscordClient(WEBHOOK, sleeper=NO_SLEEP)
    info = client.get_webhook_info()
    client.close()
    assert info["name"] == "album-bot"
    assert info["channel_id"] == "800000000000000009"


@respx.mock
def test_get_webhook_info_dead() -> None:
    respx.get(url__regex=HOST_RE).mock(return_value=httpx.Response(404, json={
        "message": "Unknown Webhook", "code": 10015,
    }))
    client = DiscordClient(WEBHOOK, sleeper=NO_SLEEP)
    with pytest.raises(WebhookDeadError):
        client.get_webhook_info()
    client.close()


@respx.mock
def test_get_webhook_info_server_error() -> None:
    respx.get(url__regex=HOST_RE).mock(return_value=httpx.Response(503))
    client = DiscordClient(WEBHOOK, sleeper=NO_SLEEP)
    with pytest.raises(TransientDiscordError):
        client.get_webhook_info()
    client.close()
