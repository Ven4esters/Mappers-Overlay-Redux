"""Релиз одной командой: версия, проверки, коммит, тег.

Зачем это нужно. Выпуск версии раньше состоял из ручных шагов: поднять номер в четырёх
местах, дописать CHANGELOG, пересобрать скриншоты, прогнать проверки, поставить тег,
приложить файлы к релизу. Каждый шаг забывается — и «забыл поднять версию в badge» видно
только на странице проекта.

Здесь выпуск — одна команда. Всё, что нельзя придумать за человека (текст изменений),
не придумывается: без раздела `## [X.Y.Z]` в CHANGELOG команда не начинает работу. Всё,
что можно проверить, проверяется до коммита, а файлы релиза (архив, SBOM, суммы) собирает
воркфлоу по тегу — туда же попадает и подпись SBOM.

Запуск::

    python -m tools.release 1.27.0 --dry-run   # показать план, ничего не менять
    python -m tools.release 1.27.0 --push      # выпустить и запушить тег
    python -m tools.release --check            # сверка версий (в CI и в тестах)
    python -m tools.release --notes v1.27.0    # текст раздела CHANGELOG для релиза
    python -m tools.release --sums build       # SHA256SUMS.txt для вложений релиза
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from map_overlay.console import use_utf8_console
from tools.make_exe_report import digests, sums_line

# subprocess вызывается только со своими командами: git и sys.executable.

ROOT: Final = Path(__file__).resolve().parent.parent
CHANGELOG: Final = Path("CHANGELOG.md")
INIT: Final = Path("map_overlay") / "__init__.py"
PYPROJECT: Final = Path("pyproject.toml")
README: Final = Path("README.md")
SUMS_NAME: Final = "SHA256SUMS.txt"
VERSION_RE: Final = re.compile(r"^\d+\.\d+\.\d+$")

#: Проверки, которые обязаны пройти до коммита: те же, что в CI, кроме Windows.
CHECKS: Final[tuple[tuple[str, ...], ...]] = (
    ("-m", "tools.check_docs"),
    ("-m", "tools.check_exceptions"),
    ("-m", "ruff", "format", "--check", "."),
    ("-m", "ruff", "check", "."),
    ("-m", "mypy"),
    ("-m", "pytest", "-o", "addopts=", "-q"),
)

#: Картинки документации пересобираются в релизе: иначе README покажет старую версию окна.
IMAGES: Final[tuple[tuple[str, ...], ...]] = (
    ("-m", "tools.make_goldens"),
    ("-m", "tools.make_screenshots"),
    ("-m", "tools.make_formulas"),
)


@dataclass(frozen=True, slots=True)
class VersionPlace:
    """Место, где живёт номер версии, и как его заменить."""

    path: Path
    pattern: re.Pattern[str]
    template: str
    #: Что видит пользователь, если место не нашлось.
    title: str

    def text(self, version: str) -> str:
        """Как выглядит строка версии после подстановки."""
        return self.template.format(version=version)

    def read(self, root: Path) -> str:
        """Содержимое файла версии."""
        text = (root / self.path).read_text(encoding="utf-8")
        match = self.pattern.search(text)
        if match is None:
            raise SystemExit(f"не нашёл номер версии в {self.path} ({self.title})")
        return match.group(1)


PLACES: Final[tuple[VersionPlace, ...]] = (
    VersionPlace(
        path=INIT,
        pattern=re.compile(r'^__version__ = "(\d+\.\d+\.\d+)"', re.MULTILINE),
        template='__version__ = "{version}"',
        title="версия пакета",
    ),
    VersionPlace(
        path=PYPROJECT,
        pattern=re.compile(r'^version = "(\d+\.\d+\.\d+)"', re.MULTILINE),
        template='version = "{version}"',
        title="версия пакета в pyproject",
    ),
    VersionPlace(
        path=README,
        pattern=re.compile(r"^Версия — (\d+\.\d+\.\d+)", re.MULTILINE),
        template="Версия — {version}",
        title="строка версии в README",
    ),
    VersionPlace(
        path=README,
        pattern=re.compile(r"badge/version-(\d+\.\d+\.\d+)-blue"),
        template="badge/version-{version}-blue",
        title="бейдж версии в README",
    ),
    VersionPlace(
        path=README,
        pattern=re.compile(r'alt="Версия (\d+\.\d+\.\d+)"'),
        template='alt="Версия {version}"',
        title="подпись бейджа версии",
    ),
)


def current_version(root: Path = ROOT) -> str:
    """Версия, записанная в пакете."""
    return PLACES[0].read(root)


def version_problems(root: Path = ROOT, *, version: str | None = None) -> list[str]:
    """Все места с версией должны показывать одно и то же."""
    expected = version or current_version(root)
    problems = [
        f"{place.path}: {place.title} показывает {place.read(root)}, а версия — {expected}"
        for place in PLACES
        if place.read(root) != expected
    ]
    if not VERSION_RE.match(expected):
        problems.append(f"версия «{expected}» не в виде X.Y.Z")
    return problems


def changelog_section(text: str, version: str) -> str | None:
    """Раздел CHANGELOG для версии вместе с заголовком; ``None`` — раздела нет."""
    heading = f"## [{version}]"
    start = text.find(heading)
    if start < 0:
        return None
    following = text.find("\n## [", start + len(heading))
    return text[start:] if following < 0 else text[start:following]


def notes(version: str, root: Path = ROOT) -> str:
    """Текст заметок о релизе: раздел CHANGELOG без служебных пометок."""
    section = changelog_section((root / CHANGELOG).read_text(encoding="utf-8"), version)
    if section is None:
        raise SystemExit(
            f"в CHANGELOG.md нет раздела «## [{version}]»: сначала опишите изменения, "
            "потом выпускайте"
        )
    return section.strip() + "\n"


def _updated(place: VersionPlace, root: Path, version: str) -> str | None:
    """Новый текст файла версии; ``None`` — файл уже такой, менять нечего."""
    text = (root / place.path).read_text(encoding="utf-8")
    updated = place.pattern.sub(lambda _match: place.text(version), text, count=1)
    return None if updated == text else updated


def planned(root: Path, version: str) -> list[Path]:
    """Файлы, которые придётся переписать для новой версии (для плана и пробного прогона)."""
    return [root / place.path for place in PLACES if _updated(place, root, version) is not None]


def bumped(root: Path, version: str) -> list[Path]:
    """Записать новую версию во все места; вернуть изменённые файлы."""
    changed: list[Path] = []
    for place in PLACES:
        updated = _updated(place, root, version)
        if updated is None:
            continue
        path = root / place.path
        path.write_text(updated, encoding="utf-8")
        if path not in changed:
            changed.append(path)
    return changed


def _call(
    command: Sequence[str], root: Path, *, check: bool = True, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Выполнить внешнюю команду в корне проекта.

    Команды собираются здесь из своих строк: список передаётся аргументами, ``shell``
    не используется, поэтому подстановка из переменных окружения в оболочку невозможна.
    """
    # Аргументы списком, без оболочки: подставить шелл-код сюда нечем.
    return subprocess.run(  # nosec B603
        command,
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
        input=stdin,
    )


def _git(
    root: Path, *args: str, check: bool = True, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Вызвать git в корне проекта."""
    return _call(["git", *args], root, check=check, stdin=stdin)


def tag_problems(root: Path, version: str) -> list[str]:
    """Тег версии не должен существовать: переписывать историю выпуском нельзя."""
    tag = f"v{version}"
    if _git(root, "tag", "--list", tag).stdout.strip():
        return [f"тег {tag} уже есть: версию переиспользовать нельзя"]
    return []


def release_problems(root: Path, version: str) -> list[str]:
    """Всё, что мешает выпуску: расхождения текущей версии, CHANGELOG, занятый тег."""
    problems = version_problems(root)
    if changelog_section((root / CHANGELOG).read_text(encoding="utf-8"), version) is None:
        problems.append(f"в CHANGELOG.md нет раздела «## [{version}]»")
    problems.extend(tag_problems(root, version))
    return problems


def run(command: Sequence[str], root: Path) -> None:
    """Выполнить команду и остановиться на первой ошибке."""
    print("→ " + " ".join(command))
    result = _call([sys.executable, *command], root, check=False)
    if result.returncode != 0:
        raise SystemExit(f"проверка не прошла: {' '.join(command)}")


def write_sums(directory: Path, root: Path = ROOT) -> Path:
    """Собрать `SHA256SUMS.txt` для вложений релиза (без самих сумм и заметок)."""
    targets = sorted(
        path
        for path in (root / directory).iterdir()
        if path.is_file() and not path.name.endswith((".sigstore", ".crt", SUMS_NAME))
    )
    if not targets:
        raise SystemExit(f"в {directory} нет файлов для сумм")
    out = root / directory / SUMS_NAME
    out.write_text("".join(sums_line(digests(path)[1], path) for path in targets), encoding="utf-8")
    return out


def _print_plan(root: Path, version: str, changed: Iterable[Path]) -> None:
    print(f"Версия: {current_version(root)} → {version}")
    for path in changed:
        print(f"  изменён {path.relative_to(root)}")
    print("Затем: проверки, картинки, коммит, тег")


def main(argv: Iterable[str] | None = None, *, root: Path = ROOT) -> int:
    """Точка входа: выпуск версии или служебные режимы для CI."""
    use_utf8_console()
    args = _parse_args(list(argv or ()))
    if args.check is not None:
        tag_version = args.check.removeprefix("v") if args.check else None
        problems = version_problems(root, version=tag_version)
        for problem in problems:
            print(problem)
        print("Версия: " + ("расхождений нет" if not problems else f"проблем: {len(problems)}"))
        return 1 if problems else 0
    if args.notes:
        print(notes(args.notes.removeprefix("v"), root), end="")
        return 0
    if args.sums:
        print(f"Суммы: {write_sums(Path(args.sums), root).relative_to(root)}")
        return 0
    if not args.version:
        print("Укажите версию: python -m tools.release 1.27.0", file=sys.stderr)
        return 2
    version = args.version.removeprefix("v")
    if not VERSION_RE.match(version):
        print(f"Версия «{version}» не в виде X.Y.Z", file=sys.stderr)
        return 2
    return _release(
        root,
        version,
        dry_run=args.dry_run,
        push=args.push,
        checks=not args.no_checks,
        images=not args.no_images,
    )


def _release(
    root: Path,
    version: str,
    *,
    dry_run: bool,
    push: bool,
    checks: bool,
    images: bool,
) -> int:
    """Сам выпуск: версия, тексты, проверки, коммит, тег, отправка."""
    problems = release_problems(root, version)
    if problems:
        for problem in problems:
            print(f"✗ {problem}")
        print("Выпуск не начат.")
        return 1
    plan = planned(root, version)
    _print_plan(root, version, plan)
    if dry_run:
        print("Пробный прогон: файлы не изменены, тег не поставлен.")
        return 0
    for path in bumped(root, version):
        print(f"  записан {path.relative_to(root)}")
    if images:
        for command in IMAGES:
            run(command, root)
    if checks:
        for command in CHECKS:
            run(command, root)
    _commit(root, version)
    tag = _tag(root, version)
    if push:
        _push(root, version)
    print(f"Готово: коммит и тег {tag}. Дальше воркфлоу Release соберёт вложения.")
    return 0


def _commit(root: Path, version: str) -> None:
    """Закоммитить версию, картинки и CHANGELOG одним «Release X.Y.Z»."""
    _git(root, "add", "-A")
    if _git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("Изменений нет: версия уже такая, коммит не нужен")
        return
    _git(root, "commit", "-m", f"Release {version}")


def _tag(root: Path, version: str) -> str:
    """Аннотированный тег, содержимое — раздел CHANGELOG.

    Сообщение идёт через stdin и ``--cleanup=whitespace``: с ``-m`` git вырезает строки,
    начинающиеся с ``#``, и заголовок раздела «## [X.Y.Z]» исчезает из тега.
    """
    tag = f"v{version}"
    _git(root, "tag", "-a", tag, "-F", "-", "--cleanup=whitespace", stdin=notes(version, root))
    return tag


def _push(root: Path, version: str) -> None:
    """Отправить коммит и тег: по тегу CI публикует релиз."""
    tag = f"v{version}"
    for ref in ("HEAD", tag):
        # Отправка идёт с выводом git: он объясняет отказ (защита ветки, чужой тег).
        print(_git(root, "push", "origin", ref).stderr.strip())


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Выпуск версии одной командой.")
    parser.add_argument("version", nargs="?", help="новая версия, например 1.27.0")
    parser.add_argument("--dry-run", action="store_true", help="только показать план")
    parser.add_argument("--push", action="store_true", help="отправить коммит и тег")
    parser.add_argument("--no-checks", action="store_true", help="не прогонять проверки")
    parser.add_argument("--no-images", action="store_true", help="не пересобирать картинки")
    parser.add_argument("--check", nargs="?", const="", help="сверка версий (можно с тегом)")
    parser.add_argument("--notes", help="напечатать раздел CHANGELOG для версии")
    parser.add_argument("--sums", help="собрать SHA256SUMS.txt в каталоге")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
