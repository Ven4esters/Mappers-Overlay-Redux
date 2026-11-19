"""OAuth2 «Подключить Discord» — Variant 2 (PKCE + local client_secret).
OAuth2 «Подключить Discord» — вариант 2 (PKCE + локальный client_secret).

The project ships a public ``client_id`` (committable). The matching
``client_secret`` is NOT in the repo — every installation needs its own
``oauth.client.json`` (see oauth.client.example.json). The PKCE verifier stays
on the device; the issued token is used once to read the ``webhook.incoming``
response and is then discarded — nothing is stored.
Публичный ``client_id`` коммитится; ``client_secret`` — только в локальном
``oauth.client.json``. Верификатор PKCE остаётся на устройстве; полученный
токен используется только чтобы прочитать ответ ``webhook.incoming`` и сразу
отбрасывается — он нигде не сохраняется.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx

from app.paths import OAUTH_CLIENT_FILE

DEFAULT_CLIENT_ID = "1572688177242574918"  # public, shipped with the app / публичный, в репо
DEFAULT_REDIRECT_PORT = 8321
CALLBACK_PATH = "/callback"
AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
SCOPE = "webhook.incoming"


# ----------------------------------------------------------------- config
@dataclass
class OAuthClientConfig:
    """Local OAuth client settings from oauth.client.json. / Локальный конфиг OAuth."""

    client_id: str
    client_secret: str
    redirect_port: int = DEFAULT_REDIRECT_PORT

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self.redirect_port}{CALLBACK_PATH}"


def load_oauth_client(path: Path | None = None) -> tuple[OAuthClientConfig | None, str]:
    """Load oauth.client.json. Returns (config, error); error is "" on success.
    Загрузить oauth.client.json. Возвращает (конфиг, ошибка); ошибка "" при успехе."""
    target = Path(path) if path else OAUTH_CLIENT_FILE
    if not target.exists():
        return None, "oauth.client.json not found / файл oauth.client.json не найден"
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"oauth.client.json is not valid JSON / Некорректный JSON: {exc}"
    if not isinstance(raw, dict):
        return None, "oauth.client.json must be a JSON object / Ожидался JSON-объект"
    client_id = str(raw.get("client_id") or DEFAULT_CLIENT_ID).strip()
    client_secret = str(raw.get("client_secret") or "").strip()
    if not client_secret or client_secret == "PASTE_CLIENT_SECRET_HERE":
        return None, "client_secret is missing in oauth.client.json / client_secret не заполнен"
    try:
        redirect_port = int(raw.get("redirect_port", DEFAULT_REDIRECT_PORT))
        if not (1 <= redirect_port <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        return None, "redirect_port must be 1..65535 / redirect_port: 1..65535"
    return OAuthClientConfig(client_id=client_id, client_secret=client_secret,
                             redirect_port=redirect_port), ""


def oauth_status(path: Path | None = None) -> dict[str, object]:
    """What the user needs to know about the local OAuth setup. / Состояние локального OAuth."""
    config, error = load_oauth_client(path)
    return {
        "configured": config is not None,
        "client_id": config.client_id if config else DEFAULT_CLIENT_ID,
        "redirect_port": config.redirect_port if config else DEFAULT_REDIRECT_PORT,
        "redirect_uri": f"http://localhost:{config.redirect_port if config else DEFAULT_REDIRECT_PORT}/callback",
        "error": error,
    }


def save_oauth_client(client_id: str, client_secret: str, redirect_port: int = DEFAULT_REDIRECT_PORT,
                      path: Path | None = None) -> tuple[bool, str]:
    """Write oauth.client.json from the app's settings form. / Сохранить oauth.client.json из формы.

    The app writes the file so the user never edits JSON by hand; it is created
    next to the app (gitignored) with owner-only permissions.
    Файл пишет само приложение: пользователь не редактирует JSON руками; файл
    создаётся рядом с приложением (в .gitignore) с правами только для владельца.
    """
    client_id = (client_id or "").strip() or DEFAULT_CLIENT_ID
    client_secret = (client_secret or "").strip()
    if not client_id.isdigit():
        return False, "client_id must be the numeric application ID / client_id — числовой ID приложения"
    if len(client_secret) < 16:
        return False, "client_secret looks too short / client_secret подозрительно короткий"
    try:
        redirect_port = int(redirect_port)
        if not (1 <= redirect_port <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        return False, "redirect_port must be 1..65535 / redirect_port: 1..65535"
    target = Path(path) if path else OAUTH_CLIENT_FILE
    payload = {"client_id": client_id, "redirect_port": redirect_port,
               "client_secret": client_secret}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except OSError as exc:
        return False, f"Could not write {target}: {exc}"
    return True, ""


def delete_oauth_client(path: Path | None = None) -> bool:
    """Remove the local OAuth config. Returns True if something was removed.
    Удалить локальный OAuth-конфиг. True, если файл был удалён."""
    target = Path(path) if path else OAUTH_CLIENT_FILE
    existed = target.exists()
    try:
        target.unlink(missing_ok=True)
        return existed
    except OSError:
        return False


# ------------------------------------------------------------------- pkce
def generate_pkce() -> tuple[str, str]:
    """(verifier, S256 challenge), urlsafe, verifier 86 chars. / (верификатор, challenge)."""
    verifier = secrets.token_urlsafe(64)  # 86 chars; 43..128 allowed
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(16)


def build_authorize_url(config: OAuthClientConfig, *, state: str, challenge: str) -> str:
    query = urlencode({
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{AUTHORIZE_URL}?{query}"


# --------------------------------------------------------------- callback
class OAuthCallbackError(RuntimeError):
    """Callback failed: denied, bad state or malformed. / Колбэк не удался."""


def parse_callback_query(query: str) -> dict[str, str]:
    """Validate ?code=&state= (or error=). / Разобрать query строки колбэка."""
    params = dict(parse_qsl(query, keep_blank_values=True))
    if "error" in params:
        detail = params.get("error_description") or params["error"]
        raise OAuthCallbackError(f"Discord declined: {detail} / Discord отклонил запрос: {detail}")
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        raise OAuthCallbackError("Callback is missing code/state / В колбэке нет code/state")
    return {"code": code, "state": state}


_CALLBACK_HTML = (
    "<!doctype html><html><head><meta charset='utf-8'><title>Screensaver → Discord</title>"
    "<style>body{background:#0B1220;color:#E5EAF5;font-family:system-ui;display:flex;"
    "align-items:center;justify-content:center;height:100vh;margin:0}"
    "div{text-align:center}h1{color:#4F7DFF}</style></head><body><div>"
    "<h1>✓ Готово / Done</h1>"
    "<p>Можете закрыть вкладку и вернуться в приложение.<br>"
    "You can close this tab and return to the app.</p>"
    "</div></body></html>"
)


def wait_for_callback(config: OAuthClientConfig, *, expected_state: str,
                      timeout: float = 180.0, abort: "threading.Event | None" = None) -> str:
    """Block until Discord redirects to the local callback; returns the code.
    Ждать редирект Discord на локальный колбэк; вернуть code.

    Raises OAuthCallbackError on error/state mismatch; TimeoutError on timeout.
    """
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_error(404)
                return
            try:
                result.update(parse_callback_query(parsed.query))
            except OAuthCallbackError as exc:
                result["error"] = str(exc)
            body = _CALLBACK_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, *_args) -> None:  # silence stdout
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", config.redirect_port), Handler)
    except OSError as exc:
        raise OAuthCallbackError(
            f"Port {config.redirect_port} is busy — free it or change redirect_port "
            f"(+ re-register the redirect URI) / Порт {config.redirect_port} занят — "
            f"освободите его или смените redirect_port (и добавьте URI в приложении Discord)") from exc

    server.timeout = 0.5
    end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            if abort is not None and abort.is_set():
                raise OAuthCallbackError("Cancelled by user / Отменено пользователем")
            server.handle_request()
            if done.is_set():
                break
        else:
            raise TimeoutError("Timed out waiting for Discord / Время ожидания истекло")
    finally:
        server.server_close()

    if "error" in result:
        raise OAuthCallbackError(result["error"])
    if result.get("state") != expected_state:
        raise OAuthCallbackError("State mismatch (possible CSRF) / Несовпадение state")
    return result["code"]


# ------------------------------------------------------------------ token
class OAuthTokenError(RuntimeError):
    """Token exchange failed. / Обмен кода на токен не удался."""


def exchange_code(config: OAuthClientConfig, *, code: str, verifier: str,
                  timeout: float = 30.0) -> dict:
    """POST the authorization code to Discord; return the parsed token response.
    Обменять authorization code на ответ токена."""
    payload = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "code_verifier": verifier,
    }
    try:
        response = httpx.post(TOKEN_URL, data=payload, timeout=timeout,
                              headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OAuthTokenError(f"Network error / Сетевая ошибка: {exc}") from exc

    if response.status_code == 200:
        try:
            data = response.json()
        except ValueError as exc:
            raise OAuthTokenError("Bad token response / Некорректный ответ Discord") from exc
        if not isinstance(data, dict):
            raise OAuthTokenError("Bad token response / Некорректный ответ Discord")
        return data

    try:
        body = response.json()
        detail = body.get("error_description") or body.get("message") or body.get("error") or ""
    except ValueError:
        detail = response.text[:200]
    raise OAuthTokenError(f"Discord rejected the exchange (HTTP {response.status_code}): {detail}")


def extract_webhook(token_response: dict) -> dict[str, str]:
    """Pull webhook url/channel/guild out of the token response. / Достать вебхук из ответа."""
    webhook = token_response.get("webhook")
    if not isinstance(webhook, dict):
        raise OAuthTokenError("No webhook in the token response — is the webhook.incoming scope granted? "
                              "/ В ответе нет объекта webhook — выдан ли scope webhook.incoming?")
    url = str(webhook.get("url") or "").strip()
    if not url:
        webhook_id, token = webhook.get("id"), webhook.get("token")
        if webhook_id and token:
            url = f"https://discord.com/api/webhooks/{webhook_id}/{token}"
    if not url:
        raise OAuthTokenError("No webhook URL in the token response / В ответе нет URL вебхука")
    return {
        "webhook_url": url,
        "channel_id": str(webhook.get("channel_id") or ""),
        "guild_id": str(webhook.get("guild_id") or ""),
    }
