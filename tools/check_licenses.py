"""Проверка лицензий установленных зависимостей: сильный копилефт блокирует сборку.

Сильный копилефт (GPL/AGPL) в зависимостях настольного приложения означает, что его
пришлось бы распространять под той же лицензией. Слабее (LGPL, MPL) для динамически
подключаемых библиотек допустим — на нём работает сам Qt.

Запуск::

    python -m tools.check_licenses
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib.metadata import distributions

STRONG_COPYLEFT: tuple[str, ...] = ("gpl", "general public license", "agpl")
# Признаки сильного копилефта в тексте лицензии.

WEAK_COPYLEFT: tuple[str, ...] = ("lesser", "lgpl", "mozilla public license", "mpl")
# Исключения: LGPL и MPL разрешают динамическое подключение проприетарного кода.

LICENSE_CLASSIFIER_PREFIX: str = "License ::"
DEFAULT_SKIP: frozenset[str] = frozenset()
# Пакеты, которые не проверяем: пусто — проверяются все установленные.


@dataclass(frozen=True, slots=True)
class Dependency:
    """Пакет и его лицензия в том виде, как её отдаёт метаданные."""

    name: str
    license: str


def license_text(metadata_license: str | None, classifiers: Iterable[str]) -> str:
    """Собрать описание лицензии из поля ``License`` и классификаторов."""
    parts = [metadata_license or ""]
    parts.extend(
        item.split("::")[-1].strip()
        for item in classifiers
        if item.startswith(LICENSE_CLASSIFIER_PREFIX)
    )
    return "; ".join(part for part in parts if part.strip())


def is_strong_copyleft(license_name: str) -> bool:
    """Сильный ли это копилефт: GPL/AGPL без «lesser» и без MPL."""
    text = license_name.lower()
    if not any(marker in text for marker in STRONG_COPYLEFT):
        return False
    return not any(marker in text for marker in WEAK_COPYLEFT)


def find_blocked(dependencies: Iterable[Dependency]) -> tuple[Dependency, ...]:
    """Зависимости с недопустимой лицензией."""
    return tuple(item for item in dependencies if is_strong_copyleft(item.license))


def installed_dependencies(skip: Iterable[str] = DEFAULT_SKIP) -> Iterator[Dependency]:
    """Обойти установленные пакеты и вернуть пары «имя — лицензия»."""
    skipped = {name.lower() for name in skip}
    for dist in sorted(distributions(), key=lambda item: item.metadata["Name"].lower()):
        metadata = dist.metadata
        name = metadata["Name"]
        if not name or name.lower() in skipped:
            continue
        yield Dependency(
            name=name,
            license=license_text(metadata["License"], metadata.get_all("Classifier") or []),
        )


def describe(dependency: Dependency) -> str:
    """Строка отчёта по одному пакету."""
    return f"{dependency.name}: {dependency.license or 'лицензия не указана'}"


def main(argv: list[str] | None = None) -> int:
    """Проверить лицензии и вернуть код выхода."""
    args = list(sys.argv[1:] if argv is None else argv)
    skip = tuple(args) or DEFAULT_SKIP
    dependencies = list(installed_dependencies(skip))
    for dependency in dependencies:
        print(describe(dependency))
    blocked = find_blocked(dependencies)
    if not blocked:
        print(f"Проверено пакетов: {len(dependencies)}, запрещённых лицензий нет")
        return 0
    for dependency in blocked:
        print(f"Запрещённая лицензия: {describe(dependency)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
