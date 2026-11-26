"""Леммы и основы слов: как сравнивать «Стену», «стены» и «wall» между собой.

Библиотека лемм лежит отдельным файлом данных (``map_overlay/data/lemmas.json``) и
подключается к поиску размеров. В файле три части:

``groups``
    Строки «лемма + все её словоформы»: ``стен`` → ``стена, стены, стеной, полустена…``.
    Лемма — короткая основа, которая и попадает в индекс поиска.

``letters``
    Замены букв, которые не различают смысл: ``ё`` → ``е`` (``проём`` = ``проем``).

``aliases``
    Пары лемм одного предмета на разных языках: ``стен`` ↔ ``wall``. Слово из пары
    находит предмет, записанный любым словом пары: «wall» находит «Стену», «стена»
    находит «Wall March».

``homoglyphs``
    Похожие буквы разных алфавитов: латинские ``a, c, e, o, p, x, y, k, m, t, h, b`` →
    кириллические ``а, с, е, о, р, х, у, к, м, т, н, в``. Применяются только к словам,
    где алфавиты смешаны: «Cтена» (латинская ``C``) найдёт «Стена», а обычное латинское
    слово «march» останется как есть.

Если слово не нашлось в словаре, работает прежнее отбрасывание окончаний (:func:`stem`),
поэтому поиск не ломается на незнакомых словах и при отсутствии файла данных.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Final

from map_overlay.errors import ConfigError

LOGGER = logging.getLogger("map_overlay.lemmas")

DATA_PACKAGE: Final = "map_overlay"
DATA_PATH: Final = "data/lemmas.json"
SCHEMA_VERSION: Final = 1

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
# Окончания для слов, которых нет в словаре. Порядок — от длинных к коротким.

DEFAULT_LETTERS: Final[Mapping[str, str]] = {"ё": "е"}
DEFAULT_HOMOGLYPHS: Final[Mapping[str, str]] = {
    "a": "а",
    "b": "в",
    "c": "с",
    "e": "е",
    "h": "н",
    "k": "к",
    "m": "м",
    "o": "о",
    "p": "р",
    "t": "т",
    "x": "х",
    "y": "у",
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "T": "Т",
    "X": "Х",
    "Y": "У",
}

_CYRILLIC: Final = frozenset("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
_LATIN: Final = frozenset("abcdefghijklmnopqrstuvwxyz")


def stem(word: str) -> str:
    """Отбросить окончание: «Стена», «стены», «стеной» → «стен».

    Запасной разбор для слов, которых нет в словаре лемм.
    """
    lowered = word.casefold()
    for ending in _ENDINGS:
        rest = len(lowered) - len(ending)
        if rest >= MIN_STEM and lowered.endswith(ending):
            return lowered[:rest]
    return lowered


@dataclass(frozen=True, slots=True)
class LemmaBook:
    """Словарь словоформ: `лемма → слова` и правила замены букв.

    Raises:
        ConfigError: если в словаре одно слово попало в две разные леммы.
    """

    lemmas: Mapping[str, str] = field(default_factory=dict)
    aliases: Mapping[str, frozenset[str]] = field(default_factory=dict)
    letters: Mapping[str, str] = field(default_factory=dict)
    homoglyphs: Mapping[str, str] = field(default_factory=dict)
    _fold: Mapping[int, str] = field(init=False, repr=False, compare=False)
    _unify: Mapping[int, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        letters = dict(self.letters) or dict(DEFAULT_LETTERS)
        homoglyphs = dict(self.homoglyphs) or dict(DEFAULT_HOMOGLYPHS)
        object.__setattr__(self, "_fold", dict(str.maketrans(letters)))
        object.__setattr__(self, "_unify", dict(str.maketrans(homoglyphs)))

    def __len__(self) -> int:
        return len(self.lemmas)

    @property
    def words(self) -> int:
        """Сколько словоформ в словаре (для тестов и диагностики)."""
        return len(self.lemmas)

    def normalize(self, word: str) -> str:
        """Привести слово к виду, в котором оно лежит в словаре."""
        return word.casefold().translate(self._fold)

    def spellings(self, word: str) -> tuple[str, ...]:
        """Варианты написания слова: как есть и, для смешанных алфавитов, с заменой букв."""
        base = self.normalize(word)
        result = [base]
        if _is_mixed(base):
            unified = base.translate(self._unify)
            if unified != base:
                result.append(unified)
        return tuple(result)

    def stems(self, word: str) -> tuple[str, ...]:
        """Основы слова: само слово, его лемма, синонимы из связок и обрезка окончания.

        Само слово в наборе обязательно: пока его набирают по буквам («Mar»), совпадение
        ищется по началу записи, а не только по лемме — иначе английское «March» с леммой
        «март» переставало бы находиться по первым буквам.
        """
        found: list[str] = []
        for spelling in self.spellings(word):
            found.append(spelling)
            lemma = self.lemmas.get(spelling)
            if lemma is None:
                found.append(stem(spelling))
                continue
            found.append(lemma)
            group = self.aliases.get(lemma)
            if group:
                found.extend(sorted(group))
        return tuple(dict.fromkeys(found))

    def has(self, word: str) -> bool:
        """Есть ли слово в словаре."""
        return any(spelling in self.lemmas for spelling in self.spellings(word))


def _is_mixed(word: str) -> bool:
    """Есть ли в слове буквы обоих алфавитов (значит, часть набрана не тем языком)."""
    letters = set(word)
    return bool(letters & _CYRILLIC) and bool(letters & _LATIN)


def read_book(path: Path) -> LemmaBook:
    """Прочитать словарь лемм из JSON-файла.

    Raises:
        ConfigError: если файл не читается или структура неверна.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Не удалось прочитать словарь лемм {path}: {exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"Словарь лемм {path} испорчен: {exc}") from exc
    return _build_book(raw, path.name)


def _build_book(raw: object, name: str) -> LemmaBook:
    """Собрать словарь из разобранного JSON: сначала проверки, потом данные."""
    data = _checked_book(raw, name)
    lemmas = _parse_lemmas(data.get("groups", []), name)
    return LemmaBook(
        lemmas=lemmas,
        aliases=_alias_groups(lemmas.values(), data.get("aliases", []), name),
        letters=_letter_map(data.get("letters")),
        homoglyphs=_letter_map(data.get("homoglyphs")),
    )


def _checked_book(raw: object, name: str) -> Mapping[str, object]:
    """Проверить общий вид словаря: объект, поддерживаемая схема, список групп.

    Raises:
        ConfigError: если структура не та или схема новее приложения.
    """
    if not isinstance(raw, Mapping):
        raise ConfigError(f"Словарь лемм {name}: ожидался объект")
    version = raw.get("schema_version", SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool) or version > SCHEMA_VERSION:
        raise ConfigError(f"Словарь лемм {name}: неподдерживаемая схема {version!r}")
    if not isinstance(raw.get("groups", []), list):
        raise ConfigError(f"Словарь лемм {name}: ожидался список групп")
    return raw


def _parse_lemmas(groups: object, name: str) -> dict[str, str]:
    """Слово → лемма по всем группам.

    Raises:
        ConfigError: если группа описана неверно или слово попало в две леммы.
    """
    lemmas: dict[str, str] = {}
    for group in groups if isinstance(groups, list) else []:
        key, words = _parse_group(group, name)
        _add_group(lemmas, key, words, name)
    return lemmas


def _parse_group(group: object, name: str) -> tuple[str, list[str]]:
    """Проверить одну группу: у неё есть лемма и список слов.

    Raises:
        ConfigError: если группа описана неверно.
    """
    if not isinstance(group, Mapping):
        raise ConfigError(f"Словарь лемм {name}: группа должна быть объектом")
    lemma = group.get("lemma")
    words = group.get("words")
    if not isinstance(lemma, str) or not lemma.strip():
        raise ConfigError(f"Словарь лемм {name}: у группы нет леммы")
    if not isinstance(words, list) or not all(isinstance(word, str) for word in words):
        raise ConfigError(f"Словарь лемм {name}: ожидался список слов у «{lemma}»")
    return lemma.strip().casefold(), words


def _add_group(lemmas: dict[str, str], key: str, words: Iterable[str], name: str) -> None:
    """Дописать слова группы, следя, чтобы слово не оказалось в двух леммах.

    Raises:
        ConfigError: если слово уже принадлежит другой лемме.
    """
    for word in words:
        folded = word.strip().casefold().replace("ё", "е")
        if not folded:
            continue
        known = lemmas.get(folded)
        if known is not None and known != key:
            raise ConfigError(
                f"Словарь лемм {name}: слово «{word}» есть и в «{known}», и в «{key}»"
            )
        lemmas[folded] = key


def _alias_groups(lemmas: Iterable[str], raw: object, name: str) -> dict[str, frozenset[str]]:
    """Собрать связки «стен ↔ wall»: для каждой леммы — все леммы её группы.

    Raises:
        ConfigError: если пара ссылается на лемму, которой нет в словаре.
    """
    pairs = _alias_pairs(raw, name)
    known = set(lemmas)
    parent: dict[str, str] = {}
    for left, right in pairs:
        for lemma in (left, right):
            if lemma not in known:
                raise ConfigError(f"Словарь лемм {name}: в связке нет леммы «{lemma}»")
        first, second = _root(parent, left), _root(parent, right)
        if first != second:
            parent[second] = first
    return _group_members(parent)


def _alias_pairs(raw: object, name: str) -> list[tuple[str, str]]:
    """Проверить связки и привести их к парам строк.

    Raises:
        ConfigError: если связка — не пара строк.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"Словарь лемм {name}: ожидался список связок")
    pairs: list[tuple[str, str]] = []
    for pair in raw:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, str) for item in pair)
        ):
            raise ConfigError(f"Словарь лемм {name}: связка должна быть парой строк")
        pairs.append((pair[0].strip().casefold(), pair[1].strip().casefold()))
    return pairs


def _root(parent: dict[str, str], lemma: str) -> str:
    """Корень группы связок: по нему видно, к какому набору относится лемма."""
    parent.setdefault(lemma, lemma)
    while parent[lemma] != lemma:
        lemma = parent[lemma]
    return lemma


def _group_members(parent: dict[str, str]) -> dict[str, frozenset[str]]:
    """Разложить связки по группам: каждая лемма знает все леммы своей группы."""
    members: dict[str, set[str]] = {}
    for lemma in parent:
        members.setdefault(_root(parent, lemma), set()).add(lemma)
    return {lemma: frozenset(group) for group in members.values() for lemma in group}


def _letter_map(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if isinstance(key, str)}


def data_path() -> Path:
    """Путь к словарю лемм внутри пакета (работает и в собранном exe)."""
    return Path(str(resources.files(DATA_PACKAGE).joinpath(DATA_PATH)))


@lru_cache(maxsize=1)
def default_book() -> LemmaBook:
    """Словарь лемм приложения; при отсутствии файла — пустой словарь и предупреждение."""
    try:
        return read_book(data_path())
    except (ConfigError, OSError, ValueError) as exc:
        LOGGER.warning("Словарь лемм недоступен, ищу только по окончаниям: %s", exc)
        return LemmaBook()


def stems_of(word: str) -> tuple[str, ...]:
    """Основы слова по словарю приложения (с запасным отбрасыванием окончаний)."""
    return default_book().stems(word)


def reset() -> None:
    """Забыть загруженный словарь (для тестов и перечитывания файла)."""
    default_book.cache_clear()


def describe(book: LemmaBook | None = None) -> str:
    """Строка для журнала: сколько словоформ загружено."""
    chosen = default_book() if book is None else book
    return f"словарь лемм: {chosen.words} словоформ"
