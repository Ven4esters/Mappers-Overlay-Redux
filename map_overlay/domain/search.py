"""Поиск по библиотеке размеров: слова-синонимы, диапазоны номеров и варианты предмета.

Название предмета часто пишут «пачкой» через запятую — перечисляя то, как предмет
называют в игре, и диапазон номеров с одинаковым габаритом::

    Стена March, TID, Hood, Soup, New, 01-39

Такая запись должна находиться по любому слову и любой их комбинации: «Стена»,
«Стена March», «Стена TID», «Стена 05» и т. п. Поэтому название разбирается на
синонимы: фрагменты через запятую, отдельные слова и — если фрагмент заканчивается
числом через дефис — весь диапазон номеров.

Варианты предмета записываются отдельными строками («Длинная стена …», «Стена с
дверным проёмом …», «Полустена …», «четверть стены …»), но ищутся по общему слову:
у слов сравниваются основы, поэтому «Стена», «стены», «стеной», «Полустена» и
«четверть стены» находятся одним запросом «стена».

Про ширину чисел: `01-39`, `001-39` и `1-39` — **разные** диапазоны. Ширина берётся
из первого числа: `01-39` даёт `01…39`, `001-10` даёт `001…010`, `1-10` даёт `1…10`.
Номер из запроса сравнивается с номерами названия точно, поэтому «Стена 01» найдёт
`01-39` и не найдёт `001-10`.

Если точных совпадений нет вовсе, номер сравнивается по значению: «Стена 1» всё-таки
найдёт `01-39` (см. ``matches(..., ignore_padding=True)``). Точная запись всегда в
приоритете: «Стена 01» покажет `01-10` и не подмешает `1-10`.

Звёздочка в запросе — «дальше любое»: она игнорируется, но не мешает: «Стена March *»
находит то же, что «Стена March».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

SEPARATORS: Final = (",", ";")
# Чем в названии разделяют синонимы: запятая — основной вариант, точка с запятой — на случай.

RANGE_LIMIT: Final = 1000
# Больше номеров не разворачиваем: «1-99999» — это опечатка, а не диапазон.

MIN_STEM: Final = 3
# Короче этого основу не режем: «Я» и «№» должны сравниваться целиком.

_ENDINGS: Final = (
    "ами",
    "ями",
    "ов",
    "ев",
    "ой",
    "ый",
    "ий",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ым",
    "им",
    "ам",
    "ям",
    "ах",
    "ях",
    "ом",
    "ем",
    "ую",
    "юю",
    "а",
    "е",
    "ё",
    "и",
    "о",
    "у",
    "ы",
    "э",
    "ю",
    "я",
    "й",
    "ь",
    "ъ",
)
# Окончания, которые отбрасываются при сравнении слов. Порядок — от длинных к коротким.

_RANGE_RE: Final = re.compile(r"(?P<prefix>.*?)(?P<start>\d+)\s*-\s*(?P<end>\d+)\s*\Z")
_WORD_RE: Final = re.compile(r"[^\s,;]+")
_WILDCARD: Final = "*"


@dataclass(frozen=True, slots=True)
class SearchIndex:
    """Разобранное название: по нему решается, подходит ли предмет под запрос."""

    stems: frozenset[str]
    """Основы слов названия и синонимов, включая «слово + номер» и номера диапазона."""

    numbers: frozenset[str]
    """Номера названия как есть: `01`, `001`, `1` — разные записи разных диапазонов."""

    values: frozenset[int]
    """Те же номера по значению: `01`, `1` → `1`. Нужны для запасного сравнения."""

    text: str
    """Название основами через пробел: по нему ищется часть слова («стен» → «Стена»)."""

    def matches(self, words: tuple[str, ...], *, ignore_padding: bool = False) -> bool:
        """Подходит ли предмет под слова запроса (все слова должны найтись).

        Args:
            words: слова запроса из :func:`parse_query`.
            ignore_padding: сравнивать номера по значению, а не по записи: «1» тогда
                совпадёт с `01`. Включается только как запасной вариант, когда точных
                совпадений нет.
        """
        for word in words:
            if word.isdigit():
                known = self.values if ignore_padding else self.numbers
                if (int(word) if ignore_padding else word) not in known:
                    return False
            elif stem(word) not in self.text:
                return False
        return True


def parse_query(text: str) -> tuple[str, ...]:
    """Разобрать строку поиска: слова в нижнем регистре, звёздочки отброшены."""
    return tuple(
        word for word in (part.casefold() for part in _WORD_RE.findall(text)) if word != _WILDCARD
    )


def stem(word: str) -> str:
    """Отбросить окончание: «Стена», «стены», «стеной» → «стен».

    Сравнение основ делает поиск устойчивым к падежам: «Стена» находит и «Длинная
    стена», и «четверть стены», и «Полустена».
    """
    lowered = word.casefold()
    for ending in _ENDINGS:
        rest = len(lowered) - len(ending)
        if rest >= MIN_STEM and lowered.endswith(ending):
            return lowered[:rest]
    return lowered


def build_index(name: str) -> SearchIndex:
    """Разобрать название предмета на синонимы, основы слов и номера диапазона."""
    stems: set[str] = set()
    numbers: set[str] = set()
    for fragment in _fragments(name):
        _add_fragment(fragment, stems, numbers)
    return SearchIndex(
        stems=frozenset(stems),
        numbers=frozenset(numbers),
        values=frozenset(int(number) for number in numbers),
        text=" ".join(sorted(stems)),
    )


def _fragments(name: str) -> list[str]:
    """Разбить название на синонимы по запятым и точкам с запятой."""
    parts = [name]
    for separator in SEPARATORS:
        parts = [piece for part in parts for piece in part.split(separator)]
    return [part.strip() for part in parts if part.strip()]


def _add_fragment(fragment: str, stems: set[str], numbers: set[str]) -> None:
    """Добавить синоним, основы его слов и развёрнутый диапазон номеров, если он есть."""
    lowered = fragment.casefold()
    stems.add(stem(lowered))
    for word in _WORD_RE.findall(lowered):
        if word.isdigit():
            numbers.add(word)
            stems.add(word)
            continue
        stems.add(stem(word))
    match = _RANGE_RE.match(lowered)
    if match is None:
        return
    start, end = match.group("start"), match.group("end")
    prefix = match.group("prefix").strip()
    for value in expand_range(start, end):
        numbers.add(value)
        stems.add(value)
        if prefix:
            stems.add(f"{stem(prefix)} {value}")


def expand_range(start: str, end: str, *, limit: int = RANGE_LIMIT) -> tuple[str, ...]:
    """Развернуть диапазон номеров, сохранив ширину первого числа.

    `01-03` → `01, 02, 03`; `001-03` → `001, 002, 003`; `1-3` → `1, 2, 3`.
    Обратный диапазон (`39-01`) разворачивается так же, как прямой. Слишком длинный
    диапазон или нечитаемые числа не разворачиваются: возвращается пустой кортеж.
    """
    if not (start.isdigit() and end.isdigit()):
        return ()
    first, last = int(start), int(end)
    if first > last:
        first, last = last, first
    if last - first + 1 > limit:
        return ()
    width = len(start)
    return tuple(str(number).zfill(width) for number in range(first, last + 1))
