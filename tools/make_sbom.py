"""SBOM релиза: перечень всех пакетов, из которых собран продукт.

Зачем это нужно. На вопрос «используем ли мы уязвимый пакет X и где именно» ответ должен
занимать минуты, а не дни. Поэтому на каждую сборку 만들вается SBOM в формате CycloneDX
(JSON) — его прикладывают к релизу и ищут по нему затронутые версии.

Запуск::

    python -m tools.make_sbom                      # build/sbom.json
    python -m tools.make_sbom --out dist/sbom.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, distributions, version
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

ROOT: Final = Path(__file__).resolve().parent.parent
PROJECT_NAME: Final = "mappers-overlay-redux"
DEFAULT_OUTPUT: Final = Path("build") / "sbom.json"
SCHEMA_VERSION: Final = "1.5"
BOM_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class Component:
    """Пакет и его версия — строка будущего SBOM."""

    name: str
    version: str

    @property
    def purl(self) -> str:
        """Package URL в форме ``pkg:pypi/имя@версия``."""
        return f"pkg:pypi/{normalise_name(self.name)}@{quote(self.version, safe='')}"


def normalise_name(name: str) -> str:
    """Имя пакета по правилам PyPI: нижний регистр, ``_`` и ``.`` → ``-``."""
    return name.lower().replace("_", "-").replace(".", "-")


def components_from(pairs: Iterable[tuple[str, str]]) -> list[Component]:
    """Собрать уникальные компоненты, отсортированные по имени.

    >>> [item.name for item in components_from([("b", "1"), ("A", "2"), ("a", "2")])]
    ['A', 'b']
    """
    unique: dict[str, Component] = {}
    for name, package_version in pairs:
        key = normalise_name(name)
        unique.setdefault(key, Component(name=name, version=package_version))
    return sorted(unique.values(), key=lambda item: normalise_name(item.name))


def installed_components() -> list[Component]:
    """Установленные в окружении пакеты — из них и состоит поставка."""
    pairs: list[tuple[str, str]] = []
    for distribution in distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        pairs.append((name, distribution.version))
    return components_from(pairs)


def project_version() -> str:
    """Версия приложения: из установленного пакета, иначе — из исходников."""
    try:
        return version(PROJECT_NAME)
    except PackageNotFoundError:
        from map_overlay import __version__

        return __version__


def build_bom(
    *,
    app_version: str,
    components: Iterable[Component],
    generated_at: str,
) -> dict[str, Any]:
    """Собрать документ CycloneDX: приложение и его зависимости."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SCHEMA_VERSION,
        "version": BOM_VERSION,
        "metadata": {
            "timestamp": generated_at,
            "tools": [{"name": "tools.make_sbom"}],
            "component": {
                "type": "application",
                "name": PROJECT_NAME,
                "version": app_version,
            },
        },
        "components": [
            {
                "type": "library",
                "name": component.name,
                "version": component.version,
                "purl": component.purl,
            }
            for component in components
        ],
    }


def now_iso() -> str:
    """Текущее время в UTC по ISO 8601 — так его понимают все SCA-инструменты."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_bom(path: Path, document: dict[str, Any]) -> None:
    """Записать SBOM: каталог создаётся, кодировка — UTF-8, отступ в два пробела."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Iterable[str] | None = None, *, root: Path = ROOT) -> int:
    """Собрать SBOM и напечатать, сколько пакетов в него попало.

    Args:
        argv: аргументы командной строки (по умолчанию — ``sys.argv[1:]``).
        root: корень проекта: относительно него лежит путь по умолчанию.
    """
    parser = argparse.ArgumentParser(description="Собрать SBOM (CycloneDX JSON)")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="куда записать SBOM")
    args = parser.parse_args(list(argv) if argv is not None else None)
    components = installed_components()
    document = build_bom(
        app_version=project_version(), components=components, generated_at=now_iso()
    )
    path = Path(args.out)
    if not path.is_absolute():
        path = root / path
    write_bom(path, document)
    print(f"SBOM: {path} — пакетов {len(components)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
