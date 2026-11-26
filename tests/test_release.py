"""Релиз одной командой: версии, заметки, суммы и воркфлоу по тегу."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from map_overlay import __version__
from tools.release import (
    CHANGELOG,
    PLACES,
    ROOT,
    SUMS_NAME,
    bumped,
    changelog_section,
    current_version,
    main,
    notes,
    planned,
    release_problems,
    version_problems,
    write_sums,
)

OLD = "1.26.0"
NEW = "9.9.9"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture(name="repo")
def repo_fixture(tmp_path: Path) -> Path:
    """Мини-репозиторий с четырьмя файлами версии и git-ом — как настоящий, только маленький."""
    (tmp_path / "map_overlay").mkdir()
    for place in PLACES:
        source = ROOT / place.path
        target = tmp_path / place.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
    (tmp_path / CHANGELOG).write_text(
        "# Журнал изменений\n\n"
        f"## [{OLD}] — 2026-11-19\n\nСтарое.\n\n"
        f"## [{NEW}] — 2026-12-01\n\nНовое.\n\n### Добавлено\n\n- релиз одной командой\n",
        encoding="utf-8",
    )
    _git(tmp_path, "init", "-q")
    # Идентичность — локальная: настоящий выпуск идёт в репозитории разработчика.
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_current_version_matches_package() -> None:
    """Скрипт читает ту же версию, что видит пользователь."""
    assert current_version() == __version__


def test_version_places_are_consistent() -> None:
    """В репозитории все места с версией показывают одно и то же."""
    assert version_problems() == []


def test_dry_run_reports_all_places(repo: Path) -> None:
    """План перечисляет каждый файл, где версия изменится."""
    places = {path.name for path in planned(repo, NEW)}
    assert places == {"__init__.py", "pyproject.toml", "README.md"}


def test_planned_keeps_files_untouched(repo: Path) -> None:
    """Планирование ничего не пишет: пробный прогон безопасен."""
    before = {path: (repo / path).read_text(encoding="utf-8") for path in (PLACES[0].path,)}
    planned(repo, NEW)
    assert (repo / PLACES[0].path).read_text(encoding="utf-8") == before[PLACES[0].path]


def test_bumped_writes_every_place(repo: Path) -> None:
    """После подъёма версии расхождений нет ни в одном месте."""
    changed = bumped(repo, NEW)
    assert changed
    assert version_problems(repo, version=NEW) == []


def test_notes_are_changelog_section() -> None:
    """Заметки о релизе — ровно раздел CHANGELOG текущей версии."""
    text = notes(__version__)
    assert text.startswith(f"## [{__version__}]")
    assert "## [1.25.0]" not in text


def test_notes_require_section(repo: Path) -> None:
    """Без раздела в CHANGELOG выпуск не начинается: текст изменений не выдумывается."""
    with pytest.raises(SystemExit):
        notes("0.0.1", repo)


def test_changelog_section_stops_at_next_version() -> None:
    """Раздел не захватывает следующую версию — иначе релиз получит чужие изменения."""
    text = f"## [{NEW}]\n\nновое\n\n## [0.0.1]\n\nстарое\n"
    section = changelog_section(text, NEW)
    assert section is not None
    assert "0.0.1" not in section


def test_existing_tag_blocks_release(repo: Path) -> None:
    """Тег уже занят — версию переиспользовать нельзя."""
    _git(repo, "tag", f"v{NEW}")
    problems = release_problems(repo, NEW)
    assert any("уже есть" in problem for problem in problems)


def test_missing_changelog_blocks_release(repo: Path) -> None:
    """Нет раздела — есть проблема, и она названа."""
    problems = release_problems(repo, "8.8.8")
    assert any("CHANGELOG" in problem for problem in problems)


def test_dry_run_changes_nothing(repo: Path) -> None:
    """`--dry-run` не меняет файлы и не ставит тег."""
    before = (repo / PLACES[0].path).read_text(encoding="utf-8")
    assert main([NEW, "--dry-run"], root=repo) == 0
    assert (repo / PLACES[0].path).read_text(encoding="utf-8") == before
    tags = subprocess.run(
        ["git", "tag", "--list"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert tags.strip() == ""


def test_release_commits_and_tags(repo: Path) -> None:
    """Настоящий выпуск: версия в файлах, коммит «Release X.Y.Z», аннотированный тег."""
    assert main([NEW, "--no-checks", "--no-images"], root=repo) == 0
    assert version_problems(repo, version=NEW) == []
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert log == f"Release {NEW}"
    tag_message = subprocess.run(
        ["git", "tag", "-n99", "--list", f"v{NEW}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "релиз одной командой" in tag_message


def test_release_refuses_without_changelog(repo: Path) -> None:
    """Нет раздела CHANGELOG — статус 1 и ни одного коммита."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert main(["7.7.7", "--no-checks", "--no-images"], root=repo) == 1
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert head == after


def test_check_mode_sees_divergence(repo: Path) -> None:
    """`--check` ловит расхождение версий: так CI не пропустит релиз с разными номерами."""
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(__version__, "1.0.0", 1), encoding="utf-8"
    )
    assert main(["--check"], root=repo) == 1


def test_check_mode_accepts_tag() -> None:
    """В CI проверка идёт по тегу: тег и версия пакета должны совпадать."""
    assert main(["--check", f"v{__version__}"]) == 0


def test_sums_cover_assets(repo: Path) -> None:
    """SHA256SUMS перечисляет вложения релиза и сам себя в список не берёт."""
    build = repo / "build"
    build.mkdir()
    for name in ("Mappers_Overlay_Redux_v9.9.9.zip", "sbom.json", "sbom.json.sigstore"):
        (build / name).write_text(name, encoding="utf-8")
    write_sums(Path("build"), repo)
    lines = (build / SUMS_NAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(tuple("0123456789abcdef"))
    assert all(SUMS_NAME not in line for line in lines)
    assert not any(line.endswith(".sigstore") for line in lines)


def test_sums_need_assets(repo: Path) -> None:
    """Пустой каталог — ошибка: пустые суммы хуже отсутствующих."""
    (repo / "build").mkdir()
    with pytest.raises(SystemExit):
        write_sums(Path("build"), repo)


def test_workflow_releases_on_tag() -> None:
    """Воркфлоу релиза: тег, права на запись, подпись SBOM и суммы среди вложений."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    assert workflow[True]["push"]["tags"] == ["v[0-9]+.[0-9]+.[0-9]+"]
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["id-token"] == "write"
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "sigstore sign" in text and "sigstore verify" in text
    assert "SHA256SUMS.txt" in text and "gh release create" in text
    assert "--notes-file build/notes.md" in text


def test_workflow_checks_tag_against_version() -> None:
    """Перед сборкой воркфлоу сверяет тег с версией в коде."""
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "tools.release --check" in text
