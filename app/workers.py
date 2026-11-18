"""Background send pipeline (QThread). / Фоновая отправка (QThread).

The worker never touches the store — it returns a plain ``SendSummary`` and the
main thread applies registration/history. Uploads run strictly sequentially.
Воркер не трогает стор: отдаёт ``SendSummary``, а главный поток обновляет
реестр и историю. Загрузка строго последовательная (рейт-лимиты Discord).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from app.discord_client import (
    DiscordClient, DiscordError, SectionInput, SectionSendError, UploadedFile, chunk_files,
)
from app.models import Album


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
