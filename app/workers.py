"""Background pipelines (QThread). / Фоновые конвейеры (QThread).

Workers never touch the store — they return a plain summary and the main
thread applies registry/history updates.
Воркеры не трогают стор: отдают summary, а главный поток обновляет реестр/историю.
"""

from __future__ import annotations

import threading
from pathlib import Path
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from app.discord_client import (
    DiscordClient, DiscordError, SectionInput, SectionSendError, UploadedFile, chunk_files,
)
from app.models import Album
from app.catbox import CatboxError, upload_file


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
class CatboxSummary:
    """Outcome of the catbox.moe upload batch. / Итог загрузки в catbox.moe."""

    status: str                       # ok | partial | failed
    urls: dict[str, str] = None       # key -> url (only successful uploads)
    errors: dict[str, str] = None     # key -> error message

    def __post_init__(self) -> None:
        self.urls = self.urls or {}
        self.errors = self.errors or {}


class CatboxUploadWorker(QThread):
    """Upload cached shots to catbox.moe without blocking the UI.
    Загружает снимки из кэша на catbox.moe, не блокируя UI.

    Signals: progress(done, total); done(CatboxSummary).
    The key is opaque to the worker — callers use it to map back to attachments.
    """

    progress = Signal(int, int)
    done = Signal(CatboxSummary)

    def __init__(self, files: list[tuple[str, str, str]], *, parent=None) -> None:
        """files: list of (key, filename, local_path). / (ключ, имя, путь)."""
        super().__init__(parent)
        self._files = list(files)
        self._abort = threading.Event()

    def abort(self) -> None:
        self._abort.set()

    def run(self) -> None:
        urls: dict[str, str] = {}
        errors: dict[str, str] = {}
        total = len(self._files)
        for index, (key, filename, local_path) in enumerate(self._files):
            if self._abort.is_set():
                break
            try:
                data = Path(local_path).read_bytes()
            except OSError as exc:
                errors[key] = str(exc)
                self.progress.emit(index + 1, total)
                continue
            try:
                urls[key] = upload_file(data, filename)
            except CatboxError as exc:
                errors[key] = str(exc)
            self.progress.emit(index + 1, total)
        if not errors:
            status = "ok"
        elif urls:
            status = "partial"
        else:
            status = "failed"
        self.done.emit(CatboxSummary(status=status, urls=urls, errors=errors))
