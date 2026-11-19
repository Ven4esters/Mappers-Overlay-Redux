"""Module 6 tests: send worker pipeline (sync, mocked client) + cache helpers.
Модуль 6: конвейер воркера отправки (синхронно, замоканный клиент) и кэш."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication

from app import cache as cache_store
from app.cache import guess_ext, mime_for_suffix, save_shot
from app.discord_client import SendResult, TransientDiscordError, UploadedFile
from app.models import Album
from app.workers import SendWorker

@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    return app or QCoreApplication([])


def make_files(n: int) -> list[UploadedFile]:
    return [UploadedFile(f"shot{i}.png", b"\x89PNG" + bytes([i]) * 8, "image/png") for i in range(n)]


def make_album() -> Album:
    return Album(id="a1", profile_id="p1", name="Дом #1644", thread_id="999000000000000001")


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[object, dict]] = []
        self.closed = False

    def send_section(self, section, **kwargs):
        self.calls.append((section, kwargs))
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return [SendResult(ok=True, message_id=f"m{i}", channel_id="thread1",
                           guild_id="guild1", message_url=f"https://discord.com/channels/guild1/thread1/m{i}",
                           attachments=[{"filename": f.filename, "url": f"https://cdn/{f.filename}"}
                                        for f in section.files])
                for i, _f in enumerate(section.files[:1])]

    def close(self):
        self.closed = True


def run_worker(qapp, worker: SendWorker) -> SendWorker:
    captured = []
    worker.done.connect(lambda summary: captured.append(summary))
    worker.run()  # synchronous — signal emitted inline on this thread
    assert len(captured) == 1
    return captured[0]


def test_single_mode_one_call(qapp) -> None:
    client = FakeClient(["ok"])
    worker = SendWorker(webhook_url="https://discord.com/api/webhooks/1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", album=make_album(),
                        files=make_files(3), section_name="Спальня", description="d",
                        style="text", send_mode="single", duplicate_caption=False,
                        client_factory=lambda _url: client)
    summary = run_worker(qapp, worker)
    assert summary.status == "ok" and summary.shots == 3
    assert len(client.calls) == 1
    assert len(client.calls[0][0].files) == 3
    assert client.closed


def test_separate_mode_caption_rules(qapp) -> None:
    client = FakeClient(["ok", "ok", "ok"])
    worker = SendWorker(webhook_url="x", album=make_album(), files=make_files(3),
                        section_name="Коридор", description="", style="text",
                        send_mode="separate", duplicate_caption=False,
                        client_factory=lambda _url: client)
    summary = run_worker(qapp, worker)
    captions = [kwargs.get("duplicate_caption") for _s, kwargs in client.calls]
    assert captions == [True, False, False]  # caption on the first message only
    assert summary.status == "ok" and summary.messages == 3


def test_separate_mode_duplicate_everywhere(qapp) -> None:
    client = FakeClient(["ok", "ok"])
    worker = SendWorker(webhook_url="x", album=make_album(), files=make_files(2),
                        section_name="S", description="", style="embed",
                        send_mode="separate", duplicate_caption=True,
                        client_factory=lambda _url: client)
    run_worker(qapp, worker)
    assert [kwargs.get("duplicate_caption") for _s, kwargs in client.calls] == [True, True]


def test_abort_before_first_part(qapp) -> None:
    client = FakeClient(["ok"])
    worker = SendWorker(webhook_url="x", album=make_album(), files=make_files(2),
                        section_name="S", description="", style="text",
                        send_mode="separate", duplicate_caption=False,
                        client_factory=lambda _url: client)
    worker.abort()
    summary = run_worker(qapp, worker)
    assert summary.status == "aborted"
    assert client.calls == []


def test_mid_batch_failure_keeps_delivered(qapp) -> None:
    client = FakeClient(["ok", TransientDiscordError("boom")])
    worker = SendWorker(webhook_url="x", album=make_album(), files=make_files(2),
                        section_name="S", description="", style="text",
                        send_mode="separate", duplicate_caption=False,
                        client_factory=lambda _url: client)
    summary = run_worker(qapp, worker)
    assert summary.status == "failed"
    assert summary.messages == 1                # first part was delivered
    assert summary.results and summary.results[0].attachments
    assert summary.error_code == "transient"


def test_guess_ext() -> None:
    assert guess_ext("image/png") == ".png"
    assert guess_ext("image/jpeg") == ".jpg"
    assert guess_ext("", "photo.WebP") == ".webp"
    assert guess_ext("application/octet-stream", "noext") == ".png"


def test_mime_for_suffix() -> None:
    assert mime_for_suffix(".jpg") == "image/jpeg"
    assert mime_for_suffix("JPEG") == "image/jpeg"
    assert mime_for_suffix(".png") == "image/png"
    assert mime_for_suffix("") == "image/png"
    assert mime_for_suffix(".bin") == "image/png"


def test_save_shot_dedupes_and_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cache_store, "cache_root", lambda: tmp_path / "shots")
    monkeypatch.setattr(cache_store, "CACHE_DIR", tmp_path)
    first = save_shot(b"same-bytes", "a.png")
    second = save_shot(b"same-bytes", "b.png")
    assert first == second
    third = save_shot(b"other", "c.png")
    assert third != first
    # clear_cache uses cache_root()
    removed, freed = cache_store.clear_cache()
    assert removed == 2 and freed > 0
