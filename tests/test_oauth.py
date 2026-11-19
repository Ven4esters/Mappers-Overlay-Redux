"""Module 8 tests: OAuth2 PKCE flow (no real Discord). / Модуль 8: OAuth2 PKCE."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time

import httpx
import pytest
import respx

import app.workers as workers_mod
from app.oauth import (
    DEFAULT_CLIENT_ID, OAuthCallbackError, OAuthClientConfig,
    OAuthTokenError, build_authorize_url, delete_oauth_client, exchange_code,
    extract_webhook, generate_pkce, generate_state, load_oauth_client,
    oauth_status, parse_callback_query, save_oauth_client, wait_for_callback,
)

CONFIG = OAuthClientConfig(client_id=DEFAULT_CLIENT_ID, client_secret="secret-123")


# ------------------------------------------------------------------- pkce
def test_pkce_shape_and_challenge() -> None:
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert all(c.isalnum() or c in "-_" for c in verifier)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert "=" not in challenge


def test_state_random() -> None:
    assert generate_state() != generate_state()


def test_authorize_url_params() -> None:
    url = build_authorize_url(CONFIG, state="st4te", challenge="chal")
    assert url.startswith("https://discord.com/api/oauth2/authorize?")
    for needle in (f"client_id={DEFAULT_CLIENT_ID}", "response_type=code",
                   "scope=webhook.incoming", "state=st4te",
                   "code_challenge=chal", "code_challenge_method=S256",
                   "redirect_uri=http"):
        assert needle in url


# ---------------------------------------------------------------- callback
def test_parse_callback_ok() -> None:
    assert parse_callback_query("code=abc&state=xyz") == {"code": "abc", "state": "xyz"}


def test_parse_callback_error() -> None:
    with pytest.raises(OAuthCallbackError):
        parse_callback_query("error=access_denied&error_description=nope")


def test_parse_callback_missing_parts() -> None:
    with pytest.raises(OAuthCallbackError):
        parse_callback_query("code=abc")
    with pytest.raises(OAuthCallbackError):
        parse_callback_query("state=xyz")


def _free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_wait_for_callback_roundtrip() -> None:
    config = OAuthClientConfig(client_id="1", client_secret="s", redirect_port=_free_port())
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["code"] = wait_for_callback(config, expected_state="state-1", timeout=10)
        except Exception as exc:  # noqa: BLE001 — captured for assertion
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{config.redirect_port}"
    response = None
    for _ in range(50):
        try:
            response = httpx.get(f"{base}/callback", params={"code": "code-9", "state": "state-1"},
                                 timeout=2.0)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    assert response is not None and response.status_code == 200
    thread.join(timeout=5)
    assert outcome.get("code") == "code-9"


def test_wait_for_callback_state_mismatch() -> None:
    config = OAuthClientConfig(client_id="1", client_secret="s", redirect_port=_free_port())
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            wait_for_callback(config, expected_state="good", timeout=10)
        except OAuthCallbackError as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{config.redirect_port}/callback",
                      params={"code": "c", "state": "bad"}, timeout=2.0)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    thread.join(timeout=5)
    assert "error" in outcome


# ------------------------------------------------------------------ config
def test_load_oauth_client_missing(tmp_path) -> None:
    config, error = load_oauth_client(tmp_path / "nope.json")
    assert config is None and error


def test_load_oauth_client_placeholder(tmp_path) -> None:
    path = tmp_path / "oauth.client.json"
    path.write_text(json.dumps({"client_id": "123", "client_secret": "PASTE_CLIENT_SECRET_HERE"}))
    config, error = load_oauth_client(path)
    assert config is None and error


def test_load_oauth_client_ok(tmp_path) -> None:
    path = tmp_path / "oauth.client.json"
    path.write_text(json.dumps({"client_secret": "shh", "redirect_port": 9999}))
    config, error = load_oauth_client(path)
    assert error == "" and config is not None
    assert config.client_id == DEFAULT_CLIENT_ID
    assert config.redirect_port == 9999
    assert config.redirect_uri == "http://localhost:9999/callback"


def test_load_oauth_client_bad_port(tmp_path) -> None:
    path = tmp_path / "oauth.client.json"
    path.write_text(json.dumps({"client_secret": "shh", "redirect_port": 70000}))
    config, error = load_oauth_client(path)
    assert config is None and error


# ------------------------------------------------------------------- token
@respx.mock
def test_exchange_code_success() -> None:
    respx.post("https://discord.com/api/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "token_type": "Bearer", "webhook": {
                "id": "100", "token": "whsec", "url": "https://discord.com/api/webhooks/100/whsec",
                "channel_id": "200", "guild_id": "300",
            },
        }))
    data = exchange_code(CONFIG, code="code-1", verifier="v")
    webhook = extract_webhook(data)
    assert webhook["webhook_url"].endswith("/100/whsec")
    assert webhook["channel_id"] == "200"
    assert webhook["guild_id"] == "300"


@respx.mock
def test_exchange_code_bad_request() -> None:
    respx.post("https://discord.com/api/oauth2/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant",
                                               "error_description": "code expired"}))
    with pytest.raises(OAuthTokenError):
        exchange_code(CONFIG, code="bad", verifier="v")


def test_extract_webhook_builds_url_from_id_token() -> None:
    webhook = extract_webhook({"webhook": {"id": "100", "token": "whsec",
                                           "channel_id": "200", "guild_id": "300"}})
    assert webhook["webhook_url"] == "https://discord.com/api/webhooks/100/whsec"


def test_extract_webhook_missing_object() -> None:
    with pytest.raises(OAuthTokenError):
        extract_webhook({"access_token": "tok"})


# ----------------------------------------------------------------- worker
def test_connect_worker_ok(qapp, monkeypatch) -> None:
    monkeypatch.setattr(workers_mod, "wait_for_callback", lambda *a, **k: "code-1")
    monkeypatch.setattr(workers_mod, "exchange_code", lambda *a, **k: {
        "webhook": {"url": "https://discord.com/api/webhooks/100/whsec",
                    "channel_id": "200", "guild_id": "300"}})
    from app.workers import ConnectDiscordWorker

    captured: dict[str, object] = {}
    worker = ConnectDiscordWorker(CONFIG, parent=None)
    worker.browserRequested.connect(lambda url: captured.setdefault("url", url))
    worker.done.connect(lambda summary: captured.setdefault("summary", summary))
    worker.run()
    summary = captured["summary"]
    assert captured["url"].startswith("https://discord.com/api/oauth2/authorize?")
    assert summary.status == "ok"
    assert summary.webhook_url.endswith("/100/whsec")
    assert summary.channel_id == "200"


def test_connect_worker_callback_timeout(qapp, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(workers_mod, "wait_for_callback", boom)
    from app.workers import ConnectDiscordWorker

    captured: dict[str, object] = {}
    worker = ConnectDiscordWorker(CONFIG, parent=None)
    worker.done.connect(lambda summary: captured.setdefault("summary", summary))
    worker.run()
    assert captured["summary"].status == "timeout"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    return app or QCoreApplication([])


# ------------------------------------------------- save/status/delete (in-app setup)
def test_save_oauth_client_roundtrip(tmp_path) -> None:
    path = tmp_path / "oauth.client.json"
    ok, error = save_oauth_client("1572688177242574918", "real-secret-value", 8321, path)
    assert ok and error == ""
    config, error = load_oauth_client(path)
    assert error == "" and config is not None
    assert config.client_id == "1572688177242574918"
    assert config.client_secret == "real-secret-value"
    assert config.redirect_port == 8321
    import stat
    if hasattr(stat, "S_IMODE"):
        import os
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_oauth_client_default_id_when_blank(tmp_path) -> None:
    path = tmp_path / "oauth.client.json"
    ok, error = save_oauth_client("  ", "real-secret-value", 8321, path)
    assert ok and error == ""
    config, _ = load_oauth_client(path)
    assert config is not None and config.client_id == DEFAULT_CLIENT_ID


def test_save_oauth_client_rejects_bad_input(tmp_path) -> None:
    path = tmp_path / "oauth.client.json"
    ok, _ = save_oauth_client("not-numeric!", "real-secret-value", 8321, path)
    assert not ok
    ok, _ = save_oauth_client("123", "short", 8321, path)
    assert not ok
    ok, _ = save_oauth_client("123", "real-secret-value", 0, path)
    assert not ok
    ok, _ = save_oauth_client("123", "real-secret-value", 70000, path)
    assert not ok
    assert not path.exists()


def test_oauth_status_reports_flags(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "oauth.client.json"
    status = oauth_status(missing)
    assert status["configured"] is False
    assert status["redirect_uri"].endswith(":8321/callback")
    ok, _ = save_oauth_client("", "real-secret-value", 9999, missing)
    assert ok
    status = oauth_status(missing)
    assert status["configured"] is True
    assert status["redirect_uri"].endswith(":9999/callback")


def test_delete_oauth_client(tmp_path) -> None:
    path = tmp_path / "oauth.client.json"
    assert delete_oauth_client(path) is False  # absent → False, no crash
    ok, _ = save_oauth_client("", "real-secret-value", 8321, path)
    assert ok and path.exists()
    assert delete_oauth_client(path) is True
    assert not path.exists()


def test_oauth_status_uses_example_shape_consistent() -> None:
    # the committed example must stay loadable-by-shape (placeholder secret aside)
    import json as _json
    import pathlib
    example = pathlib.Path("oauth.client.example.json").read_text(encoding="utf-8")
    data = _json.loads(example)
    assert set(data) == {"client_id", "redirect_port", "client_secret"}
    assert str(data["client_id"]).isdigit()
