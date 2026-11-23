"""Поиск по библиотеке: синонимы, диапазоны номеров и формы слов."""

from __future__ import annotations

import pytest
from map_overlay.domain.search import (
    RANGE_LIMIT,
    SearchIndex,
    build_index,
    expand_range,
    parse_query,
    stem,
)

WALL = "Стена March, TID, Hood, Soup, New, 01-39"


def matches(name: str, query: str) -> bool:
    """Подходит ли название под запрос."""
    return build_index(name).matches(parse_query(query))


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("01", "03", ("01", "02", "03")),
        ("001", "003", ("001", "002", "003")),
        ("1", "3", ("1", "2", "3")),
        ("09", "11", ("09", "10", "11")),
        ("03", "01", ("01", "02", "03")),
    ],
)
def test_range_keeps_width_of_first_number(start: str, end: str, expected: tuple[str, ...]) -> None:
    assert expand_range(start, end) == expected


def test_range_of_one_number() -> None:
    assert expand_range("07", "07") == ("07",)


def test_huge_range_is_not_expanded() -> None:
    assert expand_range("1", str(RANGE_LIMIT + 1)) == ()


def test_bad_range_is_not_expanded() -> None:
    assert expand_range("01", "много") == ()


def test_query_drops_wildcards_and_case() -> None:
    assert parse_query("  Стена   March * ") == ("стена", "march")


@pytest.mark.parametrize(
    "query",
    [
        "Стена",
        "Стена March",
        "Стена March *",
        "Стена TID",
        "Стена TID *",
        "стена hood",
        "Стена Soup New",
        "Стена 01",
        "Стена 02",
        "Стена 03",
        "Стена 09",
        "Стена 10",
        "Стена 39",
        "01",
        "march",
        "СТЕНА NEW",
    ],
)
def test_wall_is_found_by_any_word(query: str) -> None:
    assert matches(WALL, query)


@pytest.mark.parametrize(
    "query", ["Стена 40", "Стена 00", "Стена Склад", "Стена March TID Hood Soup New XX"]
)
def test_wall_is_not_found_by_foreign_words(query: str) -> None:
    assert not matches(WALL, query)


def test_missing_word_does_not_match_even_if_number_matches() -> None:
    assert matches(WALL, "Стена 10")
    assert not matches(WALL, "Стена 10 шкатулка")


def test_paddings_are_different_ranges() -> None:
    """01-10, 001-10 и 1-10 — разные диапазоны: номер сравнивается точно."""
    assert matches("Стена 01-10", "Стена 01")
    assert not matches("Стена 01-10", "Стена 001")
    assert not matches("Стена 001-10", "Стена 01")
    assert matches("Стена 001-10", "Стена 001")
    assert matches("Стена 001-10", "Стена 010")
    assert matches("Стена 1-10", "Стена 1")
    assert not matches("Стена 1-10", "Стена 01")


def test_range_inside_fragment() -> None:
    """Диапазон может стоять внутри синонима, а не отдельным фрагментом."""
    assert matches("Стена 05-07, склад", "Стена 06")
    assert matches("Стена 05-07, склад", "Стена 05")
    assert not matches("Стена 05-07, склад", "Стена 08")


def test_several_ranges_in_one_name() -> None:
    name = "Стена 01-03, 10-12"
    assert matches(name, "Стена 11")
    assert matches(name, "Стена 02")
    assert not matches(name, "Стена 05")


@pytest.mark.parametrize(
    "query",
    ["Стена", "стена", "Стены", "стеной", "Полустена", "Длинная стена", "четверть стены"],
)
def test_variants_are_found_by_shared_word(query: str) -> None:
    """Варианты записаны отдельными предметами, но находятся общим словом."""
    variants = [
        "Длинная стена 01-39, TID",
        "Стена с дверным проёмом 01-39, TID",
        "Полустена 01-39, TID",
        "четверть стены 01-39, TID",
    ]
    assert any(matches(name, query) for name in variants)
    assert all(matches(name, "Стена") for name in variants)


def test_variant_keeps_own_words() -> None:
    assert matches("Длинная стена 01-39", "длинная")
    assert matches("Стена с дверным проёмом 01-39", "дверным")
    assert matches("Стена с дверным проёмом 01-39", "проём")
    assert not matches("Длинная стена 01-39", "проём")


def test_stem_strips_endings() -> None:
    assert stem("Стена") == "стен"
    assert stem("стены") == "стен"
    assert stem("стеной") == "стен"
    assert stem("полустена") == "полустен"
    assert stem("01") == "01"
    assert stem("Я") == "я"


def test_word_part_matches() -> None:
    assert matches("Ящик", "ящ")
    assert matches("Паллета", "палл")


def test_semicolon_separates_synonyms() -> None:
    assert matches("Ящик; Crate; CR-01", "crate")
    assert matches("Ящик; Crate; CR-01", "ящик crate")


def test_empty_query_matches_everything() -> None:
    empty = SearchIndex(stems=frozenset(), numbers=frozenset(), values=frozenset(), text="")
    assert empty.matches(parse_query(""))


def test_reversed_range_in_name() -> None:
    assert matches("Стена 39-01", "Стена 20")


def test_unexpanded_range_is_found_as_text() -> None:
    name = f"Стена 1-{RANGE_LIMIT + 5}"
    assert matches(name, name)
    assert not matches(name, "Стена 500")


def test_loose_number_ignores_leading_zeros() -> None:
    """Запасной вариант: «Стена 1» находит запись с диапазоном «01-39»."""
    index = build_index(WALL)
    assert not index.matches(parse_query("Стена 1"))
    assert index.matches(parse_query("Стена 1"), ignore_padding=True)
    assert index.matches(parse_query("Стена 05"), ignore_padding=True)


def test_loose_number_still_rejects_foreign_number() -> None:
    index = build_index(WALL)
    assert not index.matches(parse_query("Стена 40"), ignore_padding=True)
    assert not index.matches(parse_query("Стена 0"), ignore_padding=True)


def test_loose_number_does_not_match_missing_word() -> None:
    index = build_index(WALL)
    assert not index.matches(parse_query("Стена Склад 1"), ignore_padding=True)


@pytest.mark.parametrize(
    "query",
    ["wall", "Wall", "стена", "Стена March", "стены 05"],
)
def test_wall_is_found_in_both_languages(query: str) -> None:
    """Лемма «стен» и её английская связка «wall» находят одну и ту же запись."""
    assert matches(WALL, query)


def test_english_name_is_found_by_russian_word() -> None:
    assert matches("Wall March, TID, 01-39", "стена")
    assert matches("Wall March, TID, 01-39", "март")
    assert matches("Wall March, TID, 01-39", "march")


def test_half_wall_is_not_every_wall() -> None:
    """«полустена» — отдельная лемма: запрос не подмешивает все стены."""
    assert matches("Полустена 01-39", "стена")
    assert not matches("Стена March, 01-39", "полустена")


def test_mixed_alphabet_typo_finds_wall() -> None:
    """Латинская «C» в начале слова не мешает найти «Стену»."""
    assert matches(WALL, "Cтена TID")
    assert matches(WALL, "стенa")


def test_box_is_found_by_english_synonym() -> None:
    assert matches("Ящик", "box")
    assert matches("Box", "ящик")
    assert matches("Ящик", "ящ")
