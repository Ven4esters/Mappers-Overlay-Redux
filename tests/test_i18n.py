"""Module 1 tests: i18n packs stay in sync (RU/EN). / Синхронность языковых пакетов."""

from __future__ import annotations

import json

from app.paths import I18N_DIR


def _pack(lang: str) -> dict[str, str]:
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def test_supported_packs_exist_and_parse() -> None:
    assert _pack("ru") and _pack("en")


def test_language_key_parity() -> None:
    ru, en = _pack("ru"), _pack("en")
    missing_en = set(ru) - set(en)
    missing_ru = set(en) - set(ru)
    assert not missing_en, f"EN pack is missing keys: {sorted(missing_en)}"
    assert not missing_ru, f"RU pack is missing keys: {sorted(missing_ru)}"


def test_no_empty_values() -> None:
    for lang in ("ru", "en"):
        empties = [k for k, v in _pack(lang).items() if not v.strip()]
        assert not empties, f"{lang} pack has empty values: {empties}"
