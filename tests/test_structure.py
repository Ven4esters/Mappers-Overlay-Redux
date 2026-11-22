"""Проверки структуры проекта и правил, которые нельзя доверить глазу."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from lsp_overlay import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = PROJECT_ROOT / "lsp_overlay"
EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff]")


def python_files() -> list[Path]:
    return sorted(PROJECT_ROOT.glob("lsp_overlay/**/*.py")) + sorted(
        PROJECT_ROOT.glob("tools/*.py")
    )


def test_layers_depend_inward() -> None:
    """domain не знает про Qt, application и infrastructure."""
    forbidden = (
        "PySide6",
        "lsp_overlay.ui",
        "lsp_overlay.infrastructure",
        "lsp_overlay.application",
    )
    for path in (PACKAGE / "domain").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in text, f"{path.name} не должен зависеть от {name}"


def test_application_does_not_import_infrastructure_or_qt() -> None:
    forbidden = ("PySide6", "lsp_overlay.infrastructure", "lsp_overlay.ui")
    for path in (PACKAGE / "application").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in text, f"{path.name} не должен зависеть от {name}"


def test_no_print_in_application_code() -> None:
    """В коде приложения только logging.

    Исключение — ``lsp_overlay/app.py``: там ``print`` выводит результат команды
    ``--check`` в консоль, это часть CLI, а не логирование.
    """
    for path in PACKAGE.rglob("*.py"):
        if path.name == "app.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "print(" not in text, f"print найден в {path.relative_to(PROJECT_ROOT)}"


def test_no_emoji_in_ui() -> None:
    for path in (PACKAGE / "ui").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not EMOJI.search(line), f"{path.name}:{number}: эмодзи в интерфейсе"


def test_public_modules_have_docstrings() -> None:
    for path in PACKAGE.rglob("*.py"):
        if path.name == "__init__.py" and path.stat().st_size == 0:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert ast.get_docstring(tree), f"{path.relative_to(PROJECT_ROOT)} без docstring"


def test_required_documents_exist() -> None:
    for name in (
        "README.md",
        "CONTRIBUTING.md",
        "STYLEGUIDE.md",
        "CHANGELOG.md",
        "START_HERE.txt",
        "requirements.txt",
        "requirements-dev.txt",
        "run_mapper.bat",
        "install.bat",
    ):
        assert (PROJECT_ROOT / name).exists(), f"нет файла {name}"
    for adr in (PROJECT_ROOT / "docs" / "adr").glob("*.md"):
        assert adr.stat().st_size > 200, f"{adr.name} слишком короткий"


def test_ci_runs_all_quality_gates() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for command in ("ruff format --check", "ruff check", "mypy lsp_overlay", "cov-fail-under=80"):
        assert command in workflow, f"в CI нет шага «{command}»"


def test_launcher_bat_is_ascii_and_delegates_to_bootstrap() -> None:
    content = (PROJECT_ROOT / "run_mapper.bat").read_bytes()
    assert all(byte < 128 for byte in content), "run_mapper.bat должен быть ASCII"
    text = content.decode("ascii")
    assert "tools\\bootstrap.py" in text
    assert "pause" in text, "окно консоли не должно закрываться молча"


def test_install_bat_prepares_venv_and_pauses() -> None:
    content = (PROJECT_ROOT / "install.bat").read_bytes()
    assert all(byte < 128 for byte in content), "install.bat должен быть ASCII"
    text = content.decode("ascii")
    assert "--install-only" in text
    assert ".venv" in text
    assert "pause" in text


def test_python_files_have_no_tabs_and_short_lines() -> None:
    for path in python_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert "\t" not in line, f"{path.name}:{number}: табуляция"
            assert len(line) <= 100, f"{path.name}:{number}: строка длиннее 100 символов"


def test_version_is_single_source_of_truth() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
