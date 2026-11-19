"""Module 10 smoke tests: packaging, entry point, imports, README contract.
Модуль 10: дымовые тесты — сборка, точка входа, импорты, контракт README."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _requirement_names() -> list[str]:
    names = []
    for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=;!\[]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name.lower())
    return names


def test_requirements_parse_and_are_unique() -> None:
    names = _requirement_names()
    for needed in ("pyside6", "httpx", "mss", "pillow"):
        assert needed in names, f"missing dependency: {needed}"
    assert len(names) == len(set(names)), "duplicate dependencies in requirements.txt"


def test_start_bat_contract() -> None:
    raw = (ROOT / "start.bat").read_bytes()
    assert b"\r\n" in raw, "start.bat must use CRLF line endings"
    text = raw.decode("utf-8")
    for needle in ("chcp 65001", "py -3.12", "-m venv .venv",
                   "requirements.txt", "main.py", "pause"):
        assert needle in text, f"start.bat misses: {needle}"


def test_gitattributes_pins_bat_crlf() -> None:
    assert "bat" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


def test_version_is_semver() -> None:
    import app
    assert re.match(r"^\d+\.\d+\.\d+$", app.__version__)
    assert int(app.__version__.split(".")[0]) >= 1


def test_qtfree_modules_import() -> None:
    for name in ("app.paths", "app.i18n", "app.models", "app.store", "app.webhook_url",
                 "app.discord_client", "app.albums", "app.transfer",
                 "app.bbcode", "app.catbox", "app.cache", "app.capture"):
        importlib.import_module(name)


def test_qt_modules_import_when_qt_available() -> None:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — missing system GL libs etc.
        pytest.skip(f"Qt system libraries unavailable here: {exc}")
    for name in ("app.workers", "app.ui.queue_panel", "app.ui.album_sidebar",
                 "app.ui.send_panel", "app.ui.settings_dialog", "app.ui.bbcode_dialog",
                 "app.ui.main_window", "app.ui.region_overlay", "app.hotkeys", "app.theme"):
        importlib.import_module(name)


def test_readme_roadmap_complete() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "⏳" not in text, "roadmap still has unfinished modules"
    assert "start.bat" in text


def test_gitignored_secrets_and_state() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for needle in ("config.json", "history.json", "cache/"):
        assert needle in gitignore


def test_entry_point_has_main() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    compile(source, "main.py", "exec")
    assert "def main()" in source
