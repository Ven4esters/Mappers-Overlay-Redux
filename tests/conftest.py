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


def pytest_exception_interact(node: object, call: object, report: object) -> None:
    """Показать ошибку теста аннотацией GitHub Actions.

    Зачем: журнал шага в Actions бывает недоступен (его отдаёт отдельный хост), а аннотации
    читаются через API и видны прямо в интерфейсе. Строка ``::error`` — команда раннера,
    поэтому аннотация появляется только в CI и не мешает локальному выводу.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    excinfo = getattr(call, "excinfo", None)
    if excinfo is None:
        return
    nodeid = getattr(node, "nodeid", "сбор тестов")
    message = f"{nodeid}: {excinfo.exconly()}".replace("\n", " ")[:900]
    print(f"::error title=Тест не прошёл::{message}")


def pytest_collectreport(report: object) -> None:
    """Ошибку сбора тестов тоже показывать аннотацией: иначе видно только «exit code 2»."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    if getattr(report, "failed", False):
        text = getattr(report, "longreprtext", str(report)).replace("\n", " ")[:900]
        print(f"::error title=Ошибка сбора тестов::{text}")
