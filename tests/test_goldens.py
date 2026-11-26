"""Golden-тесты интерфейса: README показывает то, что на самом деле рисует окно.

Почему так, а не «сравнить PNG с картинкой». Пиксельное сравнение ломается от шрифтов и
сглаживания, а глазами такое расхождение видно только после жалобы. Поэтому эталон
состоит из двух частей (см. ``tools.make_goldens``):

* дерево виджетов — имена, подписи, заголовки вкладок, режим «Мини»;
* сетка средних цветов снимков — смена палитры в теме видна сразу, а шрифты усредняются.

Обновление эталона — ``python -m tools.make_goldens``; тест сам ничего не переписывает,
иначе «зелёный прогон» означал бы «эталон подогнали под код».
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from tools.make_goldens import GOLDENS, build, compare

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="эталон снят на Linux: на Windows другое сглаживание шрифтов, цвета поедут",
)


@pytest.fixture(scope="module")
def snapshot(qt_app: object) -> Iterator[dict[str, object]]:
    """Фактический снимок интерфейса: собирается один раз на модуль."""
    yield build(qt_app)


@pytest.fixture(scope="module")
def golden() -> dict[str, object]:
    """Эталон из репозитория."""
    assert GOLDENS.is_file(), f"нет эталона {GOLDENS}: соберите python -m tools.make_goldens"
    return json.loads(GOLDENS.read_text(encoding="utf-8"))


def test_golden_is_regenerable(snapshot: dict[str, object], golden: dict[str, object]) -> None:
    """Интерфейс совпадает с эталоном: структура, цвета, размеры снимков."""
    problems = compare(golden, snapshot)
    assert not problems, "\n".join(problems) + "\nОбновить эталон: python -m tools.make_goldens"


def test_golden_covers_the_readme_shots(golden: dict[str, object]) -> None:
    """В эталоне есть все картинки, на которые ссылается README."""
    shots = golden["shots"]
    assert isinstance(shots, dict)
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in shots:
        assert f"screenshot-{name}.png" in text, f"README не использует screenshot-{name}.png"


def test_theme_color_change_is_visible_to_the_golden(golden: dict[str, object]) -> None:
    """Подмена цвета в теме действительно ломает сравнение.

    Тест-самопроверка: если эталон перестанет видеть палитру (например, сетка станет
    слишком грубой), основная проверка будет зелёной при любой теме — и смысла в ней нет.
    """
    import copy

    broken = copy.deepcopy(golden)
    shots = broken["shots"]
    assert isinstance(shots, dict)
    first = shots[sorted(shots)[0]]
    palette = first["palette"]
    assert isinstance(palette, list)
    for cell in palette:
        cell[0] = 255 - cell[0]
        cell[1] = 255 - cell[1]
        cell[2] = 255 - cell[2]
    problems = compare(broken, golden)
    assert any("цвет уехал" in problem for problem in problems), problems
