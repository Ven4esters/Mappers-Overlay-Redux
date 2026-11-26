"""Проверка документации: ссылки, якоря, alt-тексты, обязательные разделы, версия.

Зачем это нужно. README и docs/ стареют молча: файл переехал, заголовок переименовали,
картинка исчезла — в редакторе всё выглядит нормально, а на GitHub ссылка уже битая.
Поэтому проверки из книг «README под ключ» и «Инженерный стандарт» выполняет инструмент,
а не внимательность: битая ссылка или якорь останавливают CI.

Что проверяется:

* относительные ссылки и ``src``/``href`` ведут в существующие файлы;
* якоря ``#раздел`` совпадают с заголовками целевого файла (правила GitHub: нижний
  регистр, пробелы → дефисы, кириллица сохраняется, повторы получают ``-1``);
* у каждой картинки есть непустой ``alt``;
* в README есть обязательные разделы витрины и актуальная версия приложения.

Запуск::

    python -m tools.check_docs
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import unquote

from map_overlay import __version__
from map_overlay.console import use_utf8_console

ROOT: Final = Path(__file__).resolve().parent.parent

SKIP_FILES: Final = frozenset(
    {
        # Исходная инструкция — внешний документ, его нельзя править под наши проверки.
        "docs/instruction-code-style-and-checks.md",
    }
)
# Файлы, которые не проверяем (пути относительно корня, через «/»).

REQUIRED_README_SECTIONS: Final = (
    "Описание",
    "Возможности",
    "Требования",
    "Быстрый старт",
    "Использование",
    "Конфигурация",
    "Архитектура",
    "Тесты",
    "Лицензия",
)
# Минимальный набор разделов витрины из книги «README под ключ» (глава 2).

README_VERSION = re.compile(r"Версия\s+—\s+(\d+\.\d+\.\d+)")
README_BADGE = re.compile(r"badge/version-(\d+\.\d+\.\d+)-")
# Строка README «Версия — 1.22.0»: витрина не должна отставать от кода.

ADR_DIR: Final = Path("docs") / "adr"
ADR_TEMPLATE: Final = "0000-template.md"
ADR_FIELDS: Final = ("Владелец:", "Пересмотр:")
# У решения есть хозяин и дата пересмотра: иначе ADR превращается в архив переписки.

LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_TAG = re.compile(r"<(img|source|a)\b([^>]*)>", re.IGNORECASE)
HTML_ATTR = re.compile(r"(src|srcset|href|alt)\s*=\s*\"([^\"]*)\"", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
SCHEMES: Final = ("http://", "https://", "mailto:", "tel:", "ftp://", "data:")


@dataclass(frozen=True, slots=True)
class Problem:
    """Одна найденная проблема: где и что именно."""

    path: str
    line: int
    message: str

    def describe(self) -> str:
        """Строка для вывода: файл, строка, причина."""
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class Reference:
    """Ссылка или картинка из разметки."""

    line: int
    target: str
    text: str
    is_image: bool


INLINE_CODE = re.compile(r"`[^`\n]*`")


def mask_code(text: str) -> str:
    """Убрать код: в блоках и в обратных кавычках примеры — не ссылки и не заголовки."""
    result: list[str] = []
    inside = False
    for line in text.splitlines():
        if FENCE.match(line):
            inside = not inside
            result.append("")
            continue
        result.append("" if inside else INLINE_CODE.sub("", line))
    return "\n".join(result)


def headings(text: str) -> list[str]:
    """Заголовки ATX без блоков кода."""
    found: list[str] = []
    for line in mask_code(text).splitlines():
        match = HEADING.match(line)
        if match:
            found.append(_plain(match.group(2)))
    return found


def _plain(heading: str) -> str:
    """Убрать из заголовка разметку: ``**жирный**``, `` `код` `` и ссылки."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
    return text.replace("**", "").replace("`", "").replace("__", "").strip()


def slugify(heading: str) -> str:
    """Якорь GitHub: нижний регистр, пунктуация удалена, пробелы — дефисы."""
    text = _plain(heading).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text)


def anchors(text: str) -> set[str]:
    """Все якоря файла, включая ``-1`` у повторяющихся заголовков."""
    seen: dict[str, int] = {}
    result: set[str] = set()
    for heading in headings(text):
        base = slugify(heading)
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def _is_external(target: str) -> bool:
    """Внешняя ссылка или якорь внутри страницы: путь проверять не нужно."""
    lowered = target.lower()
    return not target or target.startswith("#") or lowered.startswith(SCHEMES)


def iter_references(text: str) -> Iterator[Reference]:
    """Ссылки и картинки в порядке появления: Markdown и inline-HTML."""
    masked = mask_code(text)
    for number, line in enumerate(masked.splitlines(), start=1):
        for match in LINK.finditer(line):
            is_image = match.group(1) == "!"
            yield Reference(
                line=number,
                target=match.group(3),
                text=match.group(2).strip(),
                is_image=is_image,
            )
        for tag in HTML_TAG.finditer(line):
            tag_name = tag.group(1).lower()
            attributes = {name.lower(): value for name, value in HTML_ATTR.findall(tag.group(2))}
            if tag_name == "a":
                yield Reference(
                    line=number,
                    target=attributes.get("href", ""),
                    text=attributes.get("alt", ""),
                    is_image=False,
                )
                continue
            source = attributes.get("srcset") or attributes.get("src", "")
            # В srcset первым идёт основной адрес, дальше — варианты плотности.
            target = source.split(",")[0].strip().split(" ")[0]
            yield Reference(
                line=number,
                target=target,
                text=attributes.get("alt", ""),
                is_image=True,
            )


def _split_target(target: str) -> tuple[str, str]:
    """Разделить ссылку на путь и якорь."""
    path, _, anchor = target.partition("#")
    return path, anchor


def _check_reference(
    reference: Reference,
    source: Path,
    root: Path,
    cache: dict[Path, set[str]],
) -> list[Problem]:
    """Проверить одну ссылку: alt, существование файла, якорь."""
    problems: list[Problem] = []
    if reference.is_image and not reference.text:
        problems.append(Problem(_relative(source, root), reference.line, "у картинки нет alt"))
    if _is_external(reference.target):
        return problems
    path_text, anchor = _split_target(reference.target)
    target = source.parent / unquote(path_text) if path_text else source
    if path_text and not target.exists():
        problems.append(Problem(_relative(source, root), reference.line, f"нет файла: {path_text}"))
        return problems
    if anchor and target.suffix.lower() == ".md" and target.exists():
        known = cache.get(target)
        if known is None:
            known = anchors(target.read_text(encoding="utf-8"))
            cache[target] = known
        if anchor.lower() not in known:
            problems.append(
                Problem(
                    _relative(source, root),
                    reference.line,
                    f"нет якоря «#{anchor}» в {_relative(target, root)}",
                )
            )
    return problems


def _relative(path: Path, root: Path) -> str:
    """Путь относительно корня через «/» — так его видно в выводе."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def check_file(path: Path, root: Path) -> list[Problem]:
    """Проверить один файл разметки."""
    text = path.read_text(encoding="utf-8")
    cache: dict[Path, set[str]] = {}
    problems: list[Problem] = []
    for reference in iter_references(text):
        problems.extend(_check_reference(reference, path, root, cache))
    return problems


def documents(root: Path) -> list[Path]:
    """Все markdown-файлы проекта, которые проверяем."""
    candidates = [root / "README.md", root / "CONTRIBUTING.md", root / "STYLEGUIDE.md"]
    candidates.extend(sorted((root / "docs").rglob("*.md")))
    files: list[Path] = []
    for item in candidates:
        if not item.exists():
            continue
        if _relative(item, root) in SKIP_FILES:
            continue
        files.append(item)
    return files


def check_readme(root: Path) -> list[Problem]:
    """Обязательные разделы витрины и актуальная версия."""
    path = root / "README.md"
    if not path.exists():
        return [Problem("README.md", 1, "файл не найден")]
    text = path.read_text(encoding="utf-8")
    present = anchors(text)
    problems = [
        Problem("README.md", 1, f"нет обязательного раздела «{title}»")
        for title in REQUIRED_README_SECTIONS
        if slugify(title) not in present
    ]
    match = README_VERSION.search(text)
    if match is None:
        problems.append(Problem("README.md", 1, "нет строки «Версия — X.Y.Z»"))
    elif match.group(1) != __version__:
        problems.append(
            Problem(
                "README.md",
                1,
                f"версия в README {match.group(1)} не совпадает с приложением {__version__}",
            )
        )
    badge = README_BADGE.search(text)
    if badge is None:
        problems.append(Problem("README.md", 1, "нет бейджа версии"))
    elif badge.group(1) != __version__:
        # Ссылка бейджа — картинка: опечатку в ней не видно, а на витрине она врёт.
        problems.append(
            Problem(
                "README.md",
                1,
                f"бейдж версии {badge.group(1)} не совпадает с приложением {__version__}",
            )
        )
    return problems


def check_adr(root: Path) -> list[Problem]:
    """У каждого ADR есть владелец и дата пересмотра (шаблон не проверяется)."""
    problems: list[Problem] = []
    for path in sorted((root / ADR_DIR).glob("*.md")):
        if path.name == ADR_TEMPLATE:
            continue
        text = path.read_text(encoding="utf-8")
        missing = [field for field in ADR_FIELDS if field not in text]
        for field in missing:
            problems.append(
                Problem(_relative(path, root), 1, f"в ADR нет поля «{field.rstrip(':')}»")
            )
    return problems


def collect_problems(root: Path = ROOT) -> list[Problem]:
    """Все проблемы документации проекта."""
    problems: list[Problem] = []
    for path in documents(root):
        problems.extend(check_file(path, root))
    problems.extend(check_readme(root))
    problems.extend(check_adr(root))
    return problems


def main(argv: Iterable[str] | None = None, *, root: Path = ROOT) -> int:
    """Точка входа: печать в UTF-8, чтобы кириллица не роняла запуск."""
    use_utf8_console()
    """Проверить документацию; 1 — если есть проблемы.

    Args:
        argv: аргументы командной строки (не используются, оставлены для единообразия).
        root: корень проекта (в тестах — временная папка).
    """
    del argv
    files = documents(root)
    problems = collect_problems(root)
    for problem in problems:
        print(problem.describe())
    print(f"Проверено файлов: {len(files)}, проблем: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
