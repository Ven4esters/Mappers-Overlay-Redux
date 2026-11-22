"""Общая настройка тестов: Qt работает без экрана."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    """Одно приложение Qt на весь прогон: второй экземпляр создать нельзя."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
