"""Общие фикстуры: Qt в offscreen-режиме и предупреждения без падений."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app() -> object:
    """Единственный QApplication на весь прогон (Qt не любит второй)."""
    pytest.importorskip("PySide6.QtWidgets", reason="PySide6 недоступен в этом окружении")
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415 - импорт после importorskip

    existing = QApplication.instance()
    return existing or QApplication([])
