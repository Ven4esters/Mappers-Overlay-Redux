"""Forum discovery tests (respx-mocked REST). / Тесты поиска публикаций (respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.forum_discovery import (
    ForumDiscoveryError, guess_last_number, list_forum_threads, get_channel_info,
)

API = "https://discord.com/api/v10"


def test_guess_last_number() -> None:
    assert guess_last_number([]) == 1
    assert guess_last_number(["Кухня | 1.png", "Кухня | 2.png", "readme.txt"]) == 3
    assert guess_last_number(["Кухня | 41.JPEG", "Кухня | 7.png"]) == 42
    assert guess_last_number(["bad | x.png", "no pipes here"]) == 1


@respx.mock
def test_list_forum_threads_merges_active_and_archived() -> None:
    respx.get(f"{API}/channels/555555555555555555/threads/active").mock(return_value=httpx.Response(
        200, json={"threads": [
            {"id": "333333333333333333", "name": "Гостиная", "message_count": 12,
             "thread_metadata": {"create_timestamp": "2024-05-02T10:00:00.000000+00:00"}},
        ]}))
    respx.get(f"{API}/channels/555555555555555555/threads/archived/public").mock(return_value=httpx.Response(
        200, json={"threads": [
            {"id": "111111111111111111", "name": "Старая публикация",
             "thread_metadata": {"create_timestamp": "2023-01-01T00:00:00.000000+00:00"}},
            {"id": "333333333333333333", "name": "Гостиная", "message_count": 12,
             "thread_metadata": {"create_timestamp": "2024-05-02T10:00:00.000000+00:00"}},
        ], "has_more": False}))
    threads = list_forum_threads("bot-token", "555555555555555555")
    ids = [t.thread_id for t in threads]
    assert ids == sorted(ids, reverse=True)          # newest first
    assert ids.count("333333333333333333") == 1      # active wins over archived dupe
    archived = next(t for t in threads if t.thread_id == "111111111111111111")
    assert archived.archived is True


@respx.mock
def test_channel_info_validates_token_and_guild() -> None:
    respx.get(f"{API}/channels/555555555555555555").mock(return_value=httpx.Response(
        200, json={"id": "555555555555555555", "name": "альбомы", "guild_id": "700000000000000001", "type": 15}))
    info = get_channel_info("bot-token", "555555555555555555")
    assert (info.is_forum, info.guild_id, info.name) == (True, "700000000000000001", "альбомы")


@respx.mock
def test_discovery_error_mapping() -> None:
    respx.get(f"{API}/channels/555555555555555555").mock(return_value=httpx.Response(401, json={"message": "401: Unauthorized"}))
    with pytest.raises(ForumDiscoveryError) as excinfo:
        get_channel_info("bad-token", "555555555555555555")
    assert excinfo.value.code == "auth"


def test_bad_snowflake_rejected() -> None:
    with pytest.raises(ForumDiscoveryError) as excinfo:
        list_forum_threads("token", "not-an-id")
    assert excinfo.value.code == "bad_id"
