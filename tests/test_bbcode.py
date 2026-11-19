"""Module 9 tests: BB-code builder, catbox.moe client, history helpers. / Модуль 9."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.bbcode import BBSection, build_bbcode, format_media
from app.catbox import CatboxError, guess_mime, upload_file
from app.models import Attachment, HistoryItem
from app.store import HistoryStore

HEADING = "[B][SIZE=6][COLOR=#FFD34D]{title}[/COLOR][/SIZE][/B]"


def test_format_media_default_img() -> None:
    assert format_media("https://x/y.png") == "[IMG]https://x/y.png[/IMG]"


def test_format_media_media_tag() -> None:
    assert format_media("https://x/y.png", "MEDIA") == "[MEDIA]https://x/y.png[/MEDIA]"


def test_format_media_custom_tag() -> None:
    assert format_media("https://x/y.png", "CUSTOM", "MYTAG") == "[MYTAG]https://x/y.png[/MYTAG]"
    assert format_media("https://x/y.png", "CUSTOM", "") == "[IMG]https://x/y.png[/IMG]"


def test_build_bbcode_layout() -> None:
    sections = [
        BBSection(name="Гостевая спальня", links=["https://cdn/1.png", "https://cdn/2.png"]),
        BBSection(name="Кухня", links=["https://cdn/3.png"]),
    ]
    text = build_bbcode("Дом #1644", sections, heading_template=HEADING)
    assert text.splitlines()[0] == "[B][SIZE=6][COLOR=#FFD34D]Дом #1644[/COLOR][/SIZE][/B]"
    assert "[B]Гостевая спальня[/B]" in text
    assert "[spoiler]\n[IMG]https://cdn/1.png[/IMG]\n[IMG]https://cdn/2.png[/IMG]\n[/spoiler]" in text
    assert text.count("[spoiler]") == 2
    # headingless spoiler: no title between [spoiler] and content
    assert "[spoiler=" not in text and "[SPOILER" not in text


def test_build_bbcode_skips_linkless_sections() -> None:
    sections = [BBSection(name="Пусто", links=[]), BBSection(name="Полно", links=["https://cdn/1.png"])]
    text = build_bbcode("T", sections, heading_template=HEADING)
    assert "[B]Пусто[/B]" not in text
    assert "[B]Полно[/B]" in text


def test_build_bbcode_ends_with_newline() -> None:
    text = build_bbcode("T", [BBSection("S", ["u"])], heading_template=HEADING)
    assert text.endswith("\n")


@respx.mock
def test_catbox_upload_ok() -> None:
    route = respx.post("https://catbox.moe/user/api.php").mock(
        return_value=httpx.Response(200, text="https://files.catbox.moe/abc123.png\n"))
    url = upload_file(b"\x89PNG", "shot.png")
    assert route.called
    assert url == "https://files.catbox.moe/abc123.png"


@respx.mock
def test_catbox_upload_rejected() -> None:
    respx.post("https://catbox.moe/user/api.php").mock(
        return_value=httpx.Response(200, text="Something went wrong."))
    with pytest.raises(CatboxError):
        upload_file(b"data", "shot.png")


@respx.mock
def test_catbox_upload_http_error() -> None:
    respx.post("https://catbox.moe/user/api.php").mock(return_value=httpx.Response(503))
    with pytest.raises(CatboxError):
        upload_file(b"data", "shot.png")


def test_catbox_guess_mime() -> None:
    assert guess_mime("a.PNG") == "image/png"
    assert guess_mime("a.jpeg") == "image/jpeg"
    assert guess_mime("a.bin") == "application/octet-stream"


def test_history_items_for_album_and_update(tmp_path, monkeypatch) -> None:
    store = HistoryStore(tmp_path / "history.json")
    ok = HistoryItem(id="h1", album_id="a1", album_name="Album", section="S",
                     attachments=[Attachment(filename="f.png", url="u", local_path="/tmp/f.png")])
    other = HistoryItem(id="h2", album_id="a2", album_name="Other", section="S",
                        attachments=[Attachment(filename="g.png", url="v")])
    failed = HistoryItem(id="h3", album_id="a1", album_name="Album", section="S",
                         status="failed")
    for item in (ok, other, failed):
        store.append(item)
    assert [i.id for i in store.items_for_album("a1")] == ["h1"]

    updated = store.update_item("h1", attachments=[Attachment(filename="f.png", url="u",
                                                              local_path="/tmp/f.png",
                                                              catbox_url="https://catbox/f.png")])
    assert updated is not None
    reloaded = HistoryStore(tmp_path / "history.json").items_for_album("a1")
    assert reloaded[0].attachments[0].catbox_url == "https://catbox/f.png"

    assert store.update_item("nope", section="x") is None
