"""catbox.moe helpers (network-free parts). / Тесты хелперов catbox.moe."""

from __future__ import annotations


def test_parse_userfiles_lines() -> None:
    from app.catbox import parse_userfiles

    text = "https://files.catbox.moe/aaaa1111.png\n\nError: nope\nhttps://files.catbox.moe/bbbb2222.jpg\n"
    assert parse_userfiles(text) == ["https://files.catbox.moe/aaaa1111.png",
                                     "https://files.catbox.moe/bbbb2222.jpg"]
    assert parse_userfiles("") == []
    assert parse_userfiles("just junk\n") == []


def test_guess_mime() -> None:
    from app.catbox import guess_mime

    assert guess_mime("shot_1.png") == "image/png"
    assert guess_mime("shot_2.JPG") == "image/jpeg"
    assert guess_mime("no_extension") == "image/png"  # documented fallback
