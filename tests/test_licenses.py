"""Лицензии зависимостей: сильный копилефт блокирует сборку."""

from __future__ import annotations

import pytest
from tools.check_licenses import (
    BUILD_ONLY,
    Dependency,
    find_blocked,
    installed_dependencies,
    is_strong_copyleft,
    license_text,
    main,
)


@pytest.mark.parametrize(
    "license_name",
    [
        "GPL-3.0",
        "GNU General Public License v3 (GPLv3)",
        "GNU Affero General Public License v3",
        "AGPL-3.0-only",
    ],
)
def test_strong_copyleft_is_blocked(license_name: str) -> None:
    assert is_strong_copyleft(license_name) is True


@pytest.mark.parametrize(
    "license_name",
    [
        "MIT License",
        "BSD License",
        "Apache-2.0",
        "GNU Library or Lesser General Public License (LGPL); Other/Proprietary License",
        "Mozilla Public License 2.0 (MPL 2.0)",
        "",
    ],
)
def test_weak_or_permissive_license_is_allowed(license_name: str) -> None:
    assert is_strong_copyleft(license_name) is False


def test_license_text_merges_field_and_classifiers() -> None:
    text = license_text(
        "MIT",
        ["Programming Language :: Python", "License :: OSI Approved :: MIT License"],
    )
    assert text == "MIT; MIT License"


def test_find_blocked_returns_only_copyleft() -> None:
    dependencies = [
        Dependency(name="pyside", license="LGPL"),
        Dependency(name="cursed", license="GPL-2.0"),
        Dependency(name="ok", license="MIT License"),
    ]
    assert [item.name for item in find_blocked(dependencies)] == ["cursed"]


def test_build_tools_are_skipped() -> None:
    """Инструменты сборки (PyInstaller) не входят в поставку и не блокируют проверку."""
    assert "pyinstaller" in BUILD_ONLY
    names = {item.name.lower() for item in installed_dependencies()}
    assert not names & BUILD_ONLY
    assert "pyside6_essentials" in names


def test_installed_environment_has_no_blocked_licenses() -> None:
    """Тот же прогон, что и в CI: сильного копилефта в зависимостях нет."""
    assert main([]) == 0
