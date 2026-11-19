"""Module 4 tests: webhook client with mocked HTTP (respx). / Тесты клиента вебхука."""

from __future__ import annotations

import re

import httpx
import pytest
import respx

from app.discord_client import (
    DiscordClient, DiscordError, ForumError, PayloadTooLargeError, RateLimitedError,
    SectionInput, SectionSendError, UploadedFile, ValidationFailedError, WebhookDeadError,
    build_content, build_embed, build_image_embed, chunk_files, dedupe_filenames,
    sanitize_filename,
)

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
HOST_RE = re.compile(r"https://discord\.com/api/webhooks/\d+/[^/?]+.*")
NO_SLEEP = lambda _s: None  # noqa: E731


def make_files(n: int, prefix: str = "shot") -> list[UploadedFile]:
    return [UploadedFile(f"{prefix}{i}.png", b"\x89PNG\r\n\x1a\n" + bytes([i]) * 16, "image/png") for i in range(n)]


def ok_message(message_id="900000000000000001", channel_id="800000000000000001",
               guild_id="700000000000000001", attachments=None):
    return httpx.Response(200, json={
        "id": message_id, "channel_id": channel_id, "guild_id": guild_id,
        "attachments": attachments if attachments is not None else
        [{"id": "a1", "filename": "shot0.png", "url": "https://cdn.discordapp.com/x.png?ex=1&is=1&hm=1"}],
    })


def make_client() -> DiscordClient:
    return DiscordClient(WEBHOOK, inter_delay=0.0, sleeper=NO_SLEEP)


# ------------------------------------------------------------ pure helpers
def test_sanitize_filename_keeps_pipe_replaces_windows_chars() -> None:
    assert sanitize_filename('a/b\\c:d*e?f"g<h>i|j.png') == "a_b_c_d_e_f_g_h_i|j.png"
    assert sanitize_filename("Гостевая спальня | 12.png") == "Гостевая спальня | 12.png"


def test_dedupe_filenames() -> None:
    files = [UploadedFile("a.png", b"1"), UploadedFile("a.png", b"2"), UploadedFile("a.png", b"3")]
    assert [f.filename for f in dedupe_filenames(files)] == ["a.png", "a-2.png", "a-3.png"]


def test_chunk_files() -> None:
    chunks = chunk_files(make_files(12))
    assert [len(c) for c in chunks] == [10, 2]
    assert chunk_files([]) == []


def test_build_content_modes() -> None:
    assert build_content("Гостевая спальня", "описание") == "**Гостевая спальня**\nописание"
    assert build_content("Гостевая спальня", "") == "**Гостевая спальня**"
    assert build_content("", "только описание") == "только описание"
    assert len(build_content("x" * 5000, "y" * 5000)) <= 2000


def test_build_embed_contract() -> None:
    embed = build_embed("t" * 300, "d" * 5000, "img.png")
    assert len(embed["title"]) == 256
    assert len(embed["description"]) == 4096
    assert embed["image"]["url"] == "attachment://img.png"
    assert embed["color"] == 0x4F7DFF


def test_build_image_embed_contract() -> None:
    embed = build_image_embed("shot1.png")
    assert embed["image"]["url"] == "attachment://shot1.png"
    assert embed["color"] == 0x4F7DFF
    assert "title" not in embed and "description" not in embed


@respx.mock
def test_send_section_embed_mode_embeds_every_image() -> None:
    route = respx.post(url__regex=HOST_RE).mock(side_effect=[ok_message()])
    client = make_client()
    client.send_section(SectionInput("Коридор", make_files(4, "Коридор | "), "второй этаж"),
                        style="embed", thread_id="800000000000000099")
    body = route.calls[0].request.content.decode("utf-8", errors="ignore")
    assert body.count("attachment://") == 4          # every image inside an embed, none left as plain attachments
    assert '"title"' in body                          # caption embed first
    assert body.count('"image"') == 4


@respx.mock
def test_send_section_embed_mode_full_chunk_caps_at_ten_embeds() -> None:
    route = respx.post(url__regex=HOST_RE).mock(side_effect=[ok_message()])
    client = make_client()
    client.send_section(SectionInput("Дом", make_files(10, "Дом | "), ""),
                        style="embed", thread_id="800000000000000099")
    body = route.calls[0].request.content.decode("utf-8", errors="ignore")
    # 1 caption embed (image 0) + 9 image-only embeds = Discord's 10-embed cap
    assert body.count('"attachment://') == 10
    assert body.count('"image"') == 10

# ------------------------------------------------------------------ sends
@respx.mock
def test_send_section_text_payload_and_attachment_names() -> None:
    route = respx.post(url__regex=HOST_RE).mock(side_effect=[ok_message()])
    client = make_client()
    files = [UploadedFile("Гостевая спальня | 1.png", b"img1"), UploadedFile("Гостевая спальня | 2.png", b"img2")]
    result = client.send_section(SectionInput("Гостевая спальня", files, "вид сверху"),
                                 style="text", thread_id="800000000000000099")
    assert result[0].ok and result[0].attachments
    request = route.calls[0].request
    assert request.url.params["thread_id"] == "800000000000000099"
    assert request.url.params["wait"] == "true"
    body = request.content
    assert b'**\xd0\x93\xd0\xbe\xd1\x81\xd1\x82\xd0' in body  # **Гос… (UTF-8)
    assert "Гостевая спальня | 1.png".encode() in body
    assert "payload_json".encode() in body


@respx.mock
def test_send_section_embed_mode() -> None:
    route = respx.post(url__regex=HOST_RE).mock(side_effect=[ok_message()])
    client = make_client()
    client.send_section(SectionInput("Коридор", make_files(1, "Коридор | "), "второй этаж"),
                        style="embed", thread_id="800000000000000099")
    body = route.calls[0].request.content.decode("utf-8", errors="ignore")
    assert '"embeds"' in body
    assert "attachment://Коридор | 0.png" in body
    assert "##" not in body  # no markdown leakage into embed path


@respx.mock
def test_chunking_caption_first_chunk_only() -> None:
    route = respx.post(url__regex=HOST_RE).mock(side_effect=[ok_message(message_id="1"), ok_message(message_id="2")])
    client = make_client()
    results = client.send_section(SectionInput("S", make_files(12), ""), style="text",
                                  thread_id="800000000000000099")
    assert len(results) == 2
    first, second = (route.calls[i].request for i in range(2))
    assert first.content.count(b"files[") >= 10 and b"files[9]" in first.content and b"files[10]" not in first.content
    assert b"files[10]" not in first.content and b"files[1]" in second.content
    assert "**S**".encode() in first.content
    assert b"**S**" not in second.content  # caption goes to the first message only


@respx.mock
def test_thread_name_creates_thread_then_chunks_go_into_it() -> None:
    route = respx.post(url__regex=HOST_RE).mock(side_effect=[
        ok_message(message_id="1", channel_id="555555555555555555"),  # new forum thread id
        ok_message(message_id="2", channel_id="555555555555555555"),
    ])
    client = make_client()
    client.send_section(SectionInput("Секция", make_files(11), ""), style="text",
                        thread_name="Альбом «Дом #1644»")
    first, second = (route.calls[i].request for i in range(2))
    assert "thread_id" not in first.url.params
    assert "thread_name" in first.content.decode("utf-8", errors="ignore")
    assert second.url.params["thread_id"] == "555555555555555555"
    assert "thread_name" not in second.content.decode("utf-8", errors="ignore")


@respx.mock
def test_429_then_success_honours_retry() -> None:
    route = respx.post(url__regex=HOST_RE).mock(side_effect=[
        httpx.Response(429, json={"retry_after": 0.01}, headers={"Retry-After": "0.01"}),
        ok_message(),
    ])
    client = make_client()
    results = client.send_section(SectionInput("S", make_files(1)), thread_id="1")
    assert results[0].ok and route.call_count == 2


@respx.mock
def test_429_exhausted_raises_rate_limited() -> None:
    respx.post(url__regex=HOST_RE).mock(side_effect=[
        httpx.Response(429, json={"retry_after": 0.01}) for _ in range(3)
    ])
    client = make_client()
    with pytest.raises(RateLimitedError):
        client.send_section(SectionInput("S", make_files(1)), thread_id="1")


@respx.mock
def test_404_means_webhook_dead() -> None:
    respx.post(url__regex=HOST_RE).mock(side_effect=[httpx.Response(404, json={"code": 10015, "message": "Unknown Webhook"})])
    client = make_client()
    with pytest.raises(WebhookDeadError):
        client.send_section(SectionInput("S", make_files(1)), thread_id="1")


@respx.mock
def test_40005_too_large() -> None:
    respx.post(url__regex=HOST_RE).mock(side_effect=[httpx.Response(400, json={"code": 40005, "message": "Request entity too large"})])
    client = make_client()
    with pytest.raises(PayloadTooLargeError):
        client.send_section(SectionInput("S", make_files(1)), thread_id="1")


@respx.mock
def test_forum_error_220001() -> None:
    respx.post(url__regex=HOST_RE).mock(side_effect=[httpx.Response(400, json={"code": 220001, "message": "Thread required"})])
    client = make_client()
    with pytest.raises(ForumError) as excinfo:
        client.send_section(SectionInput("S", make_files(1)))
    assert excinfo.value.api_code == 220001


@respx.mock
def test_partial_failure_reports_delivered() -> None:
    respx.post(url__regex=HOST_RE).mock(side_effect=[
        ok_message(message_id="1"),                      # chunk 1 OK
        httpx.Response(500), httpx.Response(500), httpx.Response(500),  # chunk 2 dies
    ])
    client = make_client()
    with pytest.raises(SectionSendError) as excinfo:
        client.send_section(SectionInput("S", make_files(12)), thread_id="1")
    assert len(excinfo.value.delivered) == 1


def test_section_requires_name_and_files() -> None:
    client = make_client()
    with pytest.raises(ValidationFailedError):
        client.send_section(SectionInput("  ", make_files(1)))
    with pytest.raises(ValidationFailedError):
        client.send_section(SectionInput("S", []))
    client.close()


@respx.mock
def test_get_webhook_message_reads_own_message() -> None:
    client = DiscordClient(WEBHOOK)
    payload = {"id": "345678901234567890", "channel_id": "234567890123456789",
               "content": "🖼️  Альбом «Кухня»\nсоздан через Screensaver → Discord"}
    respx.get(url__regex=r"https://discord\.com/api/webhooks/\d+/\w+/messages/\d+.*").mock(
        return_value=httpx.Response(200, json=payload))
    message = client.get_webhook_message("345678901234567890", thread_id="234567890123456789")
    assert message["channel_id"] == "234567890123456789"


@respx.mock
def test_get_webhook_message_failure_maps_to_discord_error() -> None:
    client = DiscordClient(WEBHOOK)
    respx.get(url__regex=r"https://discord\.com/api/webhooks/\d+/\w+/messages/\d+.*").mock(
        return_value=httpx.Response(404, json={"message": "Unknown Message"}))
    with pytest.raises(DiscordError) as excinfo:
        client.get_webhook_message("345678901234567890")
    assert excinfo.value.code == "unknown"  # base class; callers only need "unreadable"
