"""Гигиена текстовых файлов: пробелы в конце строк и перевод строки в конце файла.

Зачем это нужно. «Лишний пробел» — мелочь, которая превращается в шумный дифф: редакторы
подсвечивают такие строки, а инструменты форматирования переписывают их целыми блоками.
Пустая строка в конце файла — обратная проблема: без неё последняя строка склеивается с
выводом команды (`cat file next`), а Git рисует «\\ No newline at end of file».

Правило для Markdown мягче: два пробела в конце строки — это жёсткий перенос, они допустимы.

Запуск (pre-commit передаёт имена файлов)::

    python -m tools.check_whitespace README.md map_overlay/config.py
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

BINARY_SUFFIXES: Final = frozenset({".png", ".ico", ".zip", ".exe", ".jpg", ".jpeg", ".gif"})
# Двоичные файлы не читаем как текст: их «пробелы» — это байты данных.

SOFT_MARKDOWN: Final = frozenset({".md"})
# В Markdown два пробела в конце строки значат перенос — не трогаем.


@dataclass(frozen=True, slots=True)
class Problem:
    """Проблема в файле: номер строки и причина."""

    path: str
    line: int
    message: str

    def describe(self) -> str:
        """Строка для консоли."""
        return f"{self.path}:{self.line}: {self.message}"


def check_text(text: str, *, path: str, allow_trailing: bool) -> list[Problem]:
    """Проверить содержимое файла.

    Args:
        text: содержимое файла.
        path: путь для сообщений.
        allow_trailing: разрешены ли пробелы в конце строк (для Markdown).
    """
    problems: list[Problem] = []
    if text and not text.endswith("\n"):
        problems.append(Problem(path, text.count("\n") + 1, "нет перевода строки в конце файла"))
    if not allow_trailing:
        for number, line in enumerate(text.splitlines(), start=1):
            if line != line.rstrip():
                problems.append(Problem(path, number, "пробел в конце строки"))
    return problems


def check_file(path: Path) -> list[Problem]:
    """Проверить один файл; двоичные пропускаются."""
    if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Не текст — не наше дело: например, сгенерированный файл в другой кодировке.
        return []
    return check_text(text, path=str(path), allow_trailing=path.suffix.lower() in SOFT_MARKDOWN)


def main(argv: Iterable[str] | None = None) -> int:
    """Проверить переданные файлы; без аргументов — ничего не делать.

    Args:
        argv: имена файлов (по умолчанию — ``sys.argv[1:]``).
    """
    names = list(argv) if argv is not None else sys.argv[1:]
    problems = [problem for name in names for problem in check_file(Path(name))]
    for problem in problems:
        print(problem.describe())
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
