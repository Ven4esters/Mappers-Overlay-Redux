"""Словарь лемм: данные, загрузка, варианты написания и связки языков."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from map_overlay.domain import lemmas
from map_overlay.domain.lemmas import (
    LemmaBook,
    data_path,
    default_book,
    read_book,
    stem,
    stems_of,
)
from map_overlay.errors import ConfigError

DATA = Path(__file__).resolve().parent.parent / "map_overlay" / "data" / "lemmas.json"


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Каждый тест начинает с чистого кэша словаря."""
    lemmas.reset()
    yield
    lemmas.reset()


def test_data_file_is_present_and_big_enough() -> None:
    """Словарь лежит в пакете и покрывает лексику: это не заглушка на десять слов."""
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert len(raw["groups"]) >= 150
    assert sum(len(group["words"]) for group in raw["groups"]) >= 2000
    assert len(raw["aliases"]) >= 50


def test_data_file_has_no_duplicate_words() -> None:
    """Одно слово не может принадлежать двум разным леммам."""
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    for group in raw["groups"]:
        for word in group["words"]:
            key = word.casefold().replace("ё", "е")
            assert key not in seen or seen[key] == group["lemma"], f"{word}: {seen.get(key)}"
            seen[key] = group["lemma"]


def test_all_alias_lemmas_exist() -> None:
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    known = {group["lemma"] for group in raw["groups"]}
    for left, right in raw["aliases"]:
        assert left in known, left
        assert right in known, right


@pytest.mark.parametrize(
    ("word", "lemma"),
    [
        ("Стена", "стен"),
        ("стены", "стен"),
        ("стеной", "стен"),
        ("стенка", "стен"),
        ("Полустена", "полустен"),
        ("четверть", "четверт"),
        ("проём", "проем"),
        ("проем", "проем"),
        ("дверной", "двер"),
        ("дверца", "двер"),
        ("ящик", "ящик"),
        ("палета", "паллет"),
        ("поддон", "паллет"),
        ("стелаж", "стеллаж"),
        ("стеклопакет", "стеклопакет"),
        ("крыша", "крыш"),
        ("кирпич", "кирпич"),
        ("march", "март"),
        ("walls", "стен"),
        ("дверь", "двер"),
    ],
)
def test_known_words_map_to_lemma(word: str, lemma: str) -> None:
    assert lemma in default_book().stems(word)


def test_letter_yo_is_not_significant() -> None:
    assert stems_of("проём") == stems_of("проем") == ("проем",)
    assert stems_of("ЛЁД") == stems_of("лед")
    assert "лед" in stems_of("ЛЁД")


@pytest.mark.parametrize("word", ["Cтена", "стенa", "CТЕНА", "стeнa"])
def test_mixed_alphabet_typo_is_understood(word: str) -> None:
    """Слово, набранное в двух алфавитах, всё равно находит «стену»."""
    assert "стен" in stems_of(word)


def test_latin_word_is_not_rewritten() -> None:
    """Чисто латинское слово не превращается в кириллическое."""
    assert stems_of("TID") == ("тид",)
    assert stems_of("hood") == ("худи",)
    assert default_book().spellings("march") == ("march",)


def test_aliases_work_both_ways() -> None:
    assert "стен" in stems_of("wall") and "wall" in stems_of("стена")
    assert "двер" in stems_of("door")
    assert "box" in stems_of("Ящик")


def test_alias_chain_is_one_group() -> None:
    concrete = stems_of("concrete")
    assert {"бетон", "цемент", "concrete"} <= set(concrete)
    assert "бетон" in stems_of("cement")


def test_own_lemma_survives_aliases() -> None:
    """Своя лемма остаётся в наборе: иначе перестал бы работать поиск по части слова."""
    assert "ящик" in stems_of("box")
    assert "полустен" in stems_of("полустена")


def test_unknown_word_falls_back_to_endings() -> None:
    assert stems_of("бластер") == ("бластер",)
    assert "стен" in stems_of("стенами")


def test_short_word_is_not_cut() -> None:
    assert stem("Я") == "я"
    assert stem("это") == "это"


def test_empty_book_still_normalizes_and_strips() -> None:
    book = LemmaBook()
    assert book.words == 0
    assert book.normalize("Проём") == "проем"
    assert book.stems("Стена") == ("стен",)


def test_default_book_is_cached() -> None:
    first = default_book()
    assert first is default_book()
    assert first.words >= 2000
    lemmas.reset()
    assert default_book() is not first


def test_data_path_is_absolute_and_exists() -> None:
    path = data_path()
    assert path.is_absolute()
    assert path.name == "lemmas.json"
    assert path.is_file()


def test_read_book_works_from_any_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Собранный exe читает словарь по пути внутри пакета, а не от текущей папки."""
    copy = tmp_path / "map_overlay" / "data" / "lemmas.json"
    copy.parent.mkdir(parents=True)
    shutil.copyfile(DATA, copy)
    monkeypatch.chdir(tmp_path)
    book = read_book(copy)
    assert book.words >= 2000


def test_spec_includes_dictionary_in_build() -> None:
    """Сборка exe идёт по spec-файлу, и словарь в нём перечислен явно."""
    spec = (DATA.parent.parent.parent / "MapOverlayRedux.spec").read_text(encoding="utf-8")
    assert "map_overlay/data" in spec
    assert "lemmas.json" in spec
    assert "SystemExit" in spec


def test_build_script_uses_spec_and_checks_dictionary() -> None:
    script = (DATA.parent.parent.parent / "build_exe.bat").read_text(encoding="utf-8")
    assert "MapOverlayRedux.spec" in script
    assert "lemmas.json" in script


def test_wheel_includes_dictionary() -> None:
    """Пакет (wheel) тоже объявляет словарь как данные пакета."""
    pyproject = (DATA.parent.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.setuptools.package-data]" in pyproject
    assert "data/*.json" in pyproject


@pytest.mark.parametrize(
    "payload",
    [
        "не json",
        '{"schema_version": 2, "groups": []}',
        '{"schema_version": 1, "groups": {}}',
        '{"schema_version": 1, "groups": [{"words": []}]}',
        '{"schema_version": 1, "groups": [{"lemma": "стен", "words": "стена"}]}',
        '{"schema_version": 1, "groups": [], "aliases": [["стен"]]}',
        '{"schema_version": 1, "groups": [], "aliases": [["стен", "wall"]]}',
        (
            '{"schema_version": 1, "groups": ['
            '{"lemma": "стен", "words": ["стена"]},'
            '{"lemma": "двер", "words": ["стена"]}]}'
        ),
    ],
)
def test_broken_dictionary_is_reported(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "lemmas.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigError):
        read_book(path)


def test_missing_dictionary_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        read_book(tmp_path / "нет-такого.json")


def test_missing_dictionary_does_not_break_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без файла поиск продолжает работать по окончаниям слов."""
    monkeypatch.setattr(lemmas, "DATA_PATH", "data/нет-такого.json")
    lemmas.reset()
    assert default_book().words == 0
    assert stems_of("Стена") == ("стен",)


def test_describe_reports_size() -> None:
    text = lemmas.describe()
    assert "словарь лемм" in text
    assert str(default_book().words) in text
