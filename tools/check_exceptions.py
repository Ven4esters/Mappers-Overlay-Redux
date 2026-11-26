"""Политика исключений: просроченное или необоснованное исключение ломает CI.

Зачем это нужно. Стандарт без исключений не выживает, но исключение без владельца и
срока превращается в вечную договорённость. Поэтому отступления от правил лежат в
``docs/quality/exceptions.md`` таблицей, а этот инструмент проверяет каждую строку:

* есть причина, владелец (``@имя``) и срок снятия;
* статус — ``активно``, ``снято`` или ``просрочено``;
* у активного исключения срок ещё не прошёл — иначе CI красный.

Запуск::

    python -m tools.check_exceptions
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parent.parent
EXCEPTIONS_FILE: Final = Path("docs") / "quality" / "exceptions.md"

COLUMNS: Final = ("Правило", "Где", "Причина", "Владелец", "Срок", "Статус")
# Порядок колонок обязателен: по нему строки и разбираются.

STATUSES: Final = frozenset({"активно", "снято", "просрочено"})
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEPARATOR_RE = re.compile(r"^\|(\s*:?-{3,}:?\s*\|)+$")


@dataclass(frozen=True, slots=True)
class ExceptionRow:
    """Одно исключение из таблицы."""

    line: int
    values: tuple[str, ...]

    def field(self, name: str) -> str:
        """Значение колонки по её имени."""
        return self.values[COLUMNS.index(name)]


def split_row(line: str) -> tuple[str, ...]:
    """Разобрать строку таблицы Markdown на ячейки без обрамляющих «|»."""
    inner = line.strip().strip("|")
    return tuple(cell.strip() for cell in inner.split("|"))


def parse_rows(text: str) -> list[ExceptionRow]:
    """Все строки таблицы исключений, кроме заголовка и разделителя."""
    rows: list[ExceptionRow] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if SEPARATOR_RE.match(stripped):
            continue
        cells = split_row(stripped)
        if cells and cells[0] == COLUMNS[0]:
            continue
        rows.append(ExceptionRow(line=number, values=cells))
    return rows


def check_row(row: ExceptionRow, today: date) -> list[str]:
    """Проверить одну строку; вернуть список проблем."""
    problems: list[str] = []
    if len(row.values) != len(COLUMNS):
        return [f"ожидается {len(COLUMNS)} колонок, найдено {len(row.values)}"]
    for name in ("Правило", "Где", "Причина"):
        if not row.field(name):
            problems.append(f"пустая колонка «{name}»")
    owner = row.field("Владелец")
    if not owner.startswith("@"):
        problems.append("владелец должен быть указан как @имя")
    status = row.field("Статус").lower()
    if status not in STATUSES:
        problems.append(f"неизвестный статус «{row.field('Статус')}»")
    deadline_text = row.field("Срок")
    if not DATE_RE.match(deadline_text):
        problems.append("срок должен быть датой ГГГГ-ММ-ДД")
        return problems
    deadline = date.fromisoformat(deadline_text)
    if status == "активно" and deadline < today:
        problems.append(f"исключение просрочено {deadline.isoformat()}: снимите его или продлите")
    if status == "снято" and deadline > today:
        problems.append("снятое исключение не может иметь срок в будущем")
    return problems


def collect_problems(root: Path = ROOT, *, today: date | None = None) -> list[str]:
    """Все проблемы файла исключений (пустой список — всё в порядке)."""
    moment = today or date.today()
    path = root / EXCEPTIONS_FILE
    if not path.exists():
        return [f"нет файла {EXCEPTIONS_FILE.as_posix()}"]
    rows = parse_rows(path.read_text(encoding="utf-8"))
    problems = [
        f"{EXCEPTIONS_FILE.as_posix()}:{row.line}: {message}"
        for row in rows
        for message in check_row(row, moment)
    ]
    if not rows:
        problems.append(f"{EXCEPTIONS_FILE.as_posix()}: таблица исключений пуста или не найдена")
    return problems


def main(argv: Iterable[str] | None = None, *, root: Path = ROOT, today: date | None = None) -> int:
    """Проверить политику исключений; 1 — если есть проблемы.

    Args:
        argv: аргументы командной строки (не используются).
        root: корень проекта (в тестах — временная папка).
        today: текущая дата (в тестах — фиксированная).
    """
    del argv
    problems = collect_problems(root, today=today)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    rows = parse_rows((root / EXCEPTIONS_FILE).read_text(encoding="utf-8"))
    active = sum(1 for row in rows if row.values and row.field("Статус").lower() == "активно")
    print(f"Исключений в файле: {len(rows)}, активных: {active}, просроченных: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
