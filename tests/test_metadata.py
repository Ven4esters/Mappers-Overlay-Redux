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
