"""Background pipelines (QThread). / Фоновые конвейеры (QThread).

Workers never touch the store — they return a plain summary and the main
thread applies registry/history updates.
Воркеры не трогают стор: отдают summary, а главный поток обновляет реестр/историю.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from app.discord_client import (
    DiscordClient, DiscordError, SectionInput, SectionSendError, UploadedFile, chunk_files,
)
from app.models import Album
from app.oauth import (
    OAuthClientConfig, OAuthCallbackError, OAuthTokenError, build_authorize_url,
    exchange_code, extract_webhook, generate_pkce, generate_state, wait_for_callback,
)


@dataclass
class SendSummary:
    """What happened with the batch. / Итог пачки отправки."""

    status: str                       # ok | failed | aborted
    shots: int = 0                    # files handed to the pipeline
    messages: int = 0                 # messages actually delivered
    message_url: str = ""             # first delivered message url (if any)
    error_code: str = ""
    error_message: str = ""
    results: list = field(default_factory=list)  # delivered SendResult list (for history/attachments)


class SendWorker(QThread):
    progress = Signal(int, int)        # messages done, messages total
    done = Signal(SendSummary)

    def __init__(self, *, webhook_url: str, album: Album, files: list[UploadedFile],
                 section_name: str, description: str, style: str, send_mode: str,
                 duplicate_caption: bool, username: str = "", avatar_url: str = "",
                 client_factory=None, parent=None) -> None:
        super().__init__(parent)
        self._url = webhook_url
        self._album = album
        self._files = list(files)
        self._name = section_name
        self._description = description
        self._style = style
        self._mode = send_mode
        self._duplicate = duplicate_caption
        self._username = username or None
        self._avatar_url = avatar_url or None
        self._client_factory = client_factory
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    # ---------------------------------------------------------------- run
    def run(self) -> None:
        client = self._client_factory(self._url) if self._client_factory else DiscordClient(self._url)
        parts: list[list[UploadedFile]] = [self._files] if self._mode == "single" else [[f] for f in self._files]
        total = sum(len(chunk_files(part)) for part in parts)

        delivered: list = []
        sent = 0
        status, error_code, error_message = "ok", "", ""
        try:
            for index, part in enumerate(parts):
                if self._abort:
                    status, error_code = "aborted", "aborted"
                    error_message = "Cancelled by user / Отменено пользователем"
                    break
                try:
                    results = client.send_section(
                        SectionInput(self._name, part, self._description),
                        style=self._style, thread_id=self._album.thread_id,
                        duplicate_caption=self._duplicate or index == 0,
                        should_abort=lambda: self._abort,
                        username=self._username, avatar_url=self._avatar_url)
                except SectionSendError as exc:
                    delivered.extend(exc.delivered)
                    sent += len(exc.delivered)
                    status = "aborted" if getattr(exc, "code", "") == "aborted" else "failed"
                    cause = exc.cause or exc
                    error_code = getattr(cause, "code", "failed")
                    error_message = str(exc)
                    break
                except DiscordError as exc:
                    status, error_code, error_message = "failed", exc.code, str(exc)
                    break
                delivered.extend(results)
                sent += len(results)
                self.progress.emit(sent, total)
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001 — cleanup must never crash the worker
                pass

        summary = SendSummary(
            status=status, shots=len(self._files), messages=sent,
            message_url=next((r.message_url for r in delivered if r.message_url), ""),
            error_code=error_code, error_message=error_message, results=delivered)
        self.done.emit(summary)


@dataclass
class ConnectSummary:
    """Outcome of the «Подключить Discord» flow. / Итог потока подключения."""

    status: str                    # ok | failed | cancelled | timeout
    webhook_url: str = ""          # never logged/stored by the worker
    channel_id: str = ""
    guild_id: str = ""
    error_code: str = ""
    error_message: str = ""


class ConnectDiscordWorker(QThread):
    """Runs the OAuth2 webhook.incoming flow without blocking the UI.
    Поток OAuth2 webhook.incoming, не блокирующий UI.

    Signals: browserRequested(url) — main thread must open the system browser;
    done(ConnectSummary) — outcome (webhook URL lives only in memory).
    """

    browserRequested = Signal(str)
    done = Signal(ConnectSummary)

    def __init__(self, config: OAuthClientConfig, *, timeout: float = 180.0,
                 parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._timeout = timeout
        self._abort = threading.Event()

    def abort(self) -> None:
        self._abort.set()

    def run(self) -> None:
        verifier, challenge = generate_pkce()
        state = generate_state()
        url = build_authorize_url(self._config, state=state, challenge=challenge)
        self.browserRequested.emit(url)
        try:
            code = wait_for_callback(self._config, expected_state=state,
                                     timeout=self._timeout, abort=self._abort)
        except TimeoutError as exc:
            self.done.emit(ConnectSummary(status="timeout", error_code="timeout",
                                          error_message=str(exc)))
            return
        except OAuthCallbackError as exc:
            code_ = str(exc)
            status = "cancelled" if "Cancelled by user" in code_ else "failed"
            self.done.emit(ConnectSummary(status=status, error_code="oauth_callback",
                                          error_message=code_))
            return
        try:
            token = exchange_code(self._config, code=code, verifier=verifier)
            webhook = extract_webhook(token)
        except OAuthTokenError as exc:
            self.done.emit(ConnectSummary(status="failed", error_code="oauth_token",
                                          error_message=str(exc)))
            return
        self.done.emit(ConnectSummary(status="ok",
                                      webhook_url=webhook["webhook_url"],
                                      channel_id=webhook["channel_id"],
                                      guild_id=webhook["guild_id"]))
