"""Версия и зависимости не расходятся между файлами."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from map_overlay import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_versions_match() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in changelog


def test_requirements_match_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {_normalise(item) for item in pyproject["project"]["dependencies"]}
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    requirements = {_normalise(line) for line in lines if line and not line.startswith("#")}
    assert declared == requirements


def _normalise(requirement: str) -> str:
    return re.sub(r"\s+", "", requirement).lower()


def test_runtime_dependencies_are_ranges_not_pins() -> None:
    """Точный пин рантайма не пропускает патчи безопасности Qt.

    Проверка держит решение ADR-0049: диапазон в ``pyproject.toml``, точные версии —
    в ``requirements.lock``.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for requirement in pyproject["project"]["dependencies"]:
        assert ">=" in requirement, f"{requirement}: нужен нижний порог"
        assert "<" in requirement, f"{requirement}: нужен верхний порог"
        assert "==" not in requirement, f"{requirement}: точный пин вернулся"


def test_lock_file_covers_runtime_dependencies() -> None:
    """В lock-файле есть обе рантайм-зависимости с конкретными версиями."""
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    versions = dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;]+)", lock, flags=re.MULTILINE))
    assert versions["pyside6-essentials"].startswith("6.")
    assert versions["pyperclip"].startswith("1.")
