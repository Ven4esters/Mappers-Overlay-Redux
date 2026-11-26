"""Общая настройка тестов: Qt работает без экрана."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

_APP: QApplication | None = None
# Держим приложение в модуле, а не только в кеше фикстуры: тогда оно уничтожается
# последним и не оставляет Qt разбирать свои глобальные объекты после того, как его
# собственные статические данные уже умерли (так выглядит segfault на выходе).


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    """Одно приложение Qt на весь прогон: второй экземпляр создать нельзя."""
    global _APP
    if _APP is None:
        app = QApplication.instance()
        _APP = app if app is not None else QApplication([])
    return _APP


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    """Закрыть окна до выхода из процесса.

    Зачем: на PySide6 6.12 прогон, где созданы десятки окон, завершался segfault-ом
    уже **после** «1299 passed» — шаг CI краснел с кодом 139, хотя тесты прошли. Окна
    и приложение убираются явно, пока обвязка Qt ещё цела.
    """
    app = _APP
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


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
