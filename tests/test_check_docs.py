"""Проверка документации: битые ссылки, якоря, alt-тексты, разделы README, версия."""

from __future__ import annotations

from pathlib import Path

from map_overlay import __version__
from tools.check_docs import (
    anchors,
    check_file,
    check_readme,
    collect_problems,
    iter_references,
    main,
    slugify,
)


def test_slugify_keeps_cyrillic() -> None:
    assert slugify("Быстрый старт") == "быстрый-старт"
    assert slugify("Если Numpad не реагирует") == "если-numpad-не-реагирует"


def test_duplicate_headings_get_suffix() -> None:
    text = "# Установка\n\n## Установка\n"
    assert anchors(text) == {"установка", "установка-1"}


def test_headings_inside_code_fence_are_ignored() -> None:
    text = "```\n# не заголовок\n```\n## Заголовок\n"
    assert anchors(text) == {"заголовок"}


def test_references_found_in_markdown_and_html() -> None:
    text = (
        "![Скриншот](docs/a.png)\n" '<img src="docs/b.png" alt="Подпись">\n' "[Раздел](#раздел)\n"
    )
    targets = [item.target for item in iter_references(text)]
    assert targets == ["docs/a.png", "docs/b.png", "#раздел"]


def test_broken_relative_link_is_reported(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("![Нет файла](docs/missing.png)\n", encoding="utf-8")
    problems = check_file(tmp_path / "README.md", tmp_path)
    assert [problem.message for problem in problems] == ["нет файла: docs/missing.png"]


def test_image_without_alt_is_reported(tmp_path: Path) -> None:
    (tmp_path / "shot.png").write_bytes(b"png")
    (tmp_path / "README.md").write_text("![](shot.png)\n", encoding="utf-8")
    problems = check_file(tmp_path / "README.md", tmp_path)
    assert any("alt" in problem.message for problem in problems)


def test_broken_anchor_is_reported(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "other.md").write_text("# Другой раздел\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("[Ссылка](docs/other.md#нет-такого)\n", encoding="utf-8")
    problems = check_file(tmp_path / "README.md", tmp_path)
    assert problems and "нет якоря" in problems[0].message


def test_existing_anchor_passes(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "other.md").write_text("# Другой раздел\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("[Ссылка](docs/other.md#другой-раздел)\n", encoding="utf-8")
    assert check_file(tmp_path / "README.md", tmp_path) == []


def _readme(*sections: str, version: str = __version__, badge: str | None = None) -> str:
    body = "\n".join(f"## {title}\n" for title in sections)
    badge_version = version if badge is None else badge
    image = f"![Версия](https://img.shields.io/badge/version-{badge_version}-blue)\n\n"
    return f"{image}Версия — {version}\n\n{body}"


def test_readme_sections_and_version_pass(tmp_path: Path) -> None:
    from tools.check_docs import REQUIRED_README_SECTIONS

    (tmp_path / "README.md").write_text(_readme(*REQUIRED_README_SECTIONS), encoding="utf-8")
    assert check_readme(tmp_path) == []


def test_missing_readme_section_is_reported(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(_readme("Описание"), encoding="utf-8")
    problems = check_readme(tmp_path)
    assert any("нет обязательного раздела" in problem.message for problem in problems)


def test_stale_version_is_reported(tmp_path: Path) -> None:
    from tools.check_docs import REQUIRED_README_SECTIONS

    (tmp_path / "README.md").write_text(
        _readme(*REQUIRED_README_SECTIONS, version="0.0.1"), encoding="utf-8"
    )
    problems = check_readme(tmp_path)
    assert any("не совпадает" in problem.message for problem in problems)


def test_project_documentation_is_clean() -> None:
    """Настоящий README и docs/ проходят проверку: CI ловит регресс, а не только тесты."""
    assert collect_problems() == []


def test_main_returns_zero_on_clean_project(tmp_path: Path) -> None:
    from tools.check_docs import REQUIRED_README_SECTIONS

    (tmp_path / "README.md").write_text(_readme(*REQUIRED_README_SECTIONS), encoding="utf-8")
    assert main([], root=tmp_path) == 0


def test_adr_without_owner_is_reported(tmp_path: Path) -> None:
    from tools.check_docs import check_adr

    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-example.md").write_text("# ADR-0001. Пример\n\n## Контекст\n", encoding="utf-8")
    problems = check_adr(tmp_path)
    assert len(problems) == 2
    assert all("в ADR нет поля" in problem.message for problem in problems)


def test_adr_template_is_not_checked(tmp_path: Path) -> None:
    from tools.check_docs import check_adr

    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0000-template.md").write_text("# Шаблон\n", encoding="utf-8")
    assert check_adr(tmp_path) == []


def test_stale_badge_version_is_reported(tmp_path: Path) -> None:
    """Опечатка в ссылке бейджа видна только на витрине — проверка обязана её ловить."""
    from tools.check_docs import REQUIRED_README_SECTIONS

    (tmp_path / "README.md").write_text(
        _readme(*REQUIRED_README_SECTIONS, badge="0.0.1"), encoding="utf-8"
    )
    problems = check_readme(tmp_path)
    assert any("бейдж версии" in problem.message for problem in problems)


def test_missing_badge_is_reported(tmp_path: Path) -> None:
    from tools.check_docs import REQUIRED_README_SECTIONS

    body = "\n".join(f"## {title}\n" for title in REQUIRED_README_SECTIONS)
    (tmp_path / "README.md").write_text(f"Версия — {__version__}\n\n{body}", encoding="utf-8")
    problems = check_readme(tmp_path)
    assert any("нет бейджа версии" in problem.message for problem in problems)
