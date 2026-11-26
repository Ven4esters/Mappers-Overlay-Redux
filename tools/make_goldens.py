"""Эталоны интерфейса для golden-тестов: структура окна и его цвета.

Зачем. Скриншоты в README собираются из настоящего окна, но проверить их в тесте
«глазами» нельзя, а расхождение с интерфейсом ловилось только вручную: в 1.22.x README
показывал старую версию окна. Здесь из того же окна снимаются две вещи:

* **структура** — дерево видимых виджетов с именами, подписями и заголовками вкладок:
  ловит переименованную вкладку, пропавшую кнопку, спрятанное поле. От размеров не
  зависит, поэтому проходит на разных шрифтах;
* **цвета** — сетка средних цветов PNG: ловит подмену цвета в теме. Усреднение по крупным
  клеткам убирает влияние шрифтов и сглаживания, а смена палитры видна сразу.

Файл ``tests/goldens/ui.json`` пересобирается одной командой::

    python -m tools.make_goldens

Масштаб снимка — 1 (без ``QT_SCALE_FACTOR``), как в тестах: иначе эталон и проверка
рисовали бы разные картинки.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parent.parent
GOLDENS: Final = ROOT / "tests" / "goldens" / "ui.json"

#: Масштаб эталона: совпадает с pytest, где ``QT_SCALE_FACTOR`` не выставлен.
GOLDEN_SCALE: Final = 1
#: Сетка средних цветов: 12×12 клеток по ~100 px — шрифт внутри клетки «размывается».
PALETTE_CELLS: Final = 12
#: Каждый второй пиксель: среднее по клетке от этого не меняется, а прогон быстрее.
PALETTE_STEP: Final = 2
#: Цвет считается заметным, если занимает хотя бы эту долю снимка (промилле).
COLOR_SHARE: Final = 0.2
#: Порог присутствия: столько пикселей цвета должно остаться в снимке, чтобы он считался
#: «на месте». Ниже — уже шум сглаживания, а не исчезнувший цвет темы.
COLOR_PRESENT: Final = 0.02
#: Порог «нового» цвета: он должен занимать заметную площадь. Иначе достаточно градиента
#: сглаживания, который на другом растеризаторе случайно попал в допуск.
COLOR_NEW: Final = 1.0
#: Насколько пиксель может отличаться от цвета темы и всё ещё считаться им. Растеризаторы
#: текста на разных ОС дают чуть разные оттенки одного и того же цвета темы; допуск делает
#: проверку независимой от шрифтов.
COLOR_TOLERANCE: Final = 12
#: Насколько доля цвета может разойтись между прогонами: шрифты меняют число пикселей
#: внутри глифов, но не сам набор цветов темы.
COLOR_SHARE_TOLERANCE: Final = 0.5

#: Виджеты, у которых подпись — часть интерфейса, а не демонстрационные данные.
TEXT_TYPES: Final = (
    "QAbstractButton",
    "QCheckBox",
    "QGroupBox",
    "QLabel",
    "QRadioButton",
)


def palette(
    pixmap: object, *, cells: int = PALETTE_CELLS, step: int = PALETTE_STEP
) -> list[list[int]]:
    """Средние цвета по сетке ``cells × cells``: ``[r, g, b]`` на клетку, слева направо.

    Картинка переводится в ``RGB32``: тогда пиксель занимает ровно четыре байта, и сумма
    считается по буферу, без вызова ``pixelColor`` на каждый пиксель.
    """
    from PySide6.QtGui import QImage  # импорт внутри: модуль нужен и без Qt (проверки доков)

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)  # type: ignore[attr-defined]
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    bits = image.constBits()
    cell_w = max(width // cells, 1)
    cell_h = max(height // cells, 1)
    result: list[list[int]] = []
    for row in range(cells):
        for col in range(cells):
            left, top = col * cell_w, row * cell_h
            total_r = total_g = total_b = count = 0
            for y in range(top, min(top + cell_h, height), step):
                base = y * stride
                for x in range(left, min(left + cell_w, width), step):
                    offset = base + x * 4
                    total_b += bits[offset]
                    total_g += bits[offset + 1]
                    total_r += bits[offset + 2]
                    count += 1
            if not count:
                result.append([0, 0, 0])
                continue
            result.append([round(total_r / count), round(total_g / count), round(total_b / count)])
    return result


def theme_colors(pixmap: object, *, step: int = PALETTE_STEP) -> dict[str, float]:
    """Доли цветов темы на снимке: ``"#rrggbb" → промилле``.

    Считаются только цвета из ``ui/theme.py`` (с допуском ``COLOR_TOLERANCE``): остальное —
    сглаживание и шрифты, и их доля меняется от машины к машине. Плоские области (фон,
    поверхности, рамки) и сплошные акценты от шрифта не зависят, поэтому подмена цвета в
    теме видна сразу: старого цвета в снимке не остаётся.
    """
    from PySide6.QtGui import QImage  # импорт внутри: модуль нужен и без Qt

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)  # type: ignore[attr-defined]
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    bits = image.constBits()
    palette = theme_palette()
    counts = dict.fromkeys(palette, 0)
    nearest: dict[int, str | None] = {}
    total = 0
    for y in range(0, height, step):
        base = y * stride
        for x in range(0, width, step):
            offset = base + x * 4
            red, green, blue = bits[offset + 2], bits[offset + 1], bits[offset]
            key = (red >> 2) << 12 | (green >> 2) << 6 | (blue >> 2)
            color = nearest.get(key, "")
            if color == "":
                color = _nearest(palette, red, green, blue)
                nearest[key] = color
            if color is not None:
                counts[color] += 1
            total += 1
    return {color: round(count / total * 1000, 3) for color, count in sorted(counts.items())}


def _nearest(palette: tuple[str, ...], red: int, green: int, blue: int) -> str | None:
    """Ближайший цвет темы в пределах допуска; ``None`` — пиксель не из палитры."""
    best: str | None = None
    best_distance = COLOR_TOLERANCE + 1
    for color in palette:
        dr = abs(int(color[1:3], 16) - red)
        dg = abs(int(color[3:5], 16) - green)
        db = abs(int(color[5:7], 16) - blue)
        distance = max(dr, dg, db)
        if distance < best_distance:
            best, best_distance = color, distance
    return best


def theme_palette() -> tuple[str, ...]:
    """Цвета из ``ui/theme.py``: имена констант вида ``ACCENT = "#3b82f6"``."""
    from map_overlay.ui import theme

    return tuple(
        value.lower()
        for value in vars(theme).values()
        if isinstance(value, str) and value.startswith("#") and len(value) == 7
    )


def _text_of(widget: object, version: str) -> str:
    """Подпись виджета, если она есть и не зависит от версии приложения."""
    if type(widget).__name__ not in TEXT_TYPES:
        return ""
    text = str(getattr(widget, "text", lambda: "")()).replace("\n", " ").strip()
    return "" if not text or version in text else text


def window_tree(root: object, version: str) -> list[str]:
    """Дерево видимых виджетов окна: отступ, класс, имя объекта, подпись.

    Скрытые виджеты пропускаются: «спрятали поле» — это изменение, но его видно и по
    отсутствию строки, а держать в эталоне невидимые внутренние объекты Qt незачем.
    """
    from PySide6.QtWidgets import QTabWidget  # импорт внутри: см. palette

    lines: list[str] = []

    def walk(widget: object, depth: int) -> None:
        for child in widget.children():  # type: ignore[attr-defined]
            # hasattr сужает тип: дальше mypy знает, что у объекта есть isVisible.
            if not hasattr(child, "isVisible") or not child.isVisible():
                continue
            entry = f"{'  ' * depth}{type(child).__name__}"
            name = child.objectName()
            if name:
                entry += f"#{name}"
            text = _text_of(child, version)
            if text:
                entry += f" '{text}'"
            lines.append(entry)
            if isinstance(child, QTabWidget):
                lines.extend(
                    f"{'  ' * (depth + 1)}tab '{child.tabText(index)}'"
                    for index in range(child.count())
                )
            walk(child, depth + 1)

    walk(root, 0)
    return lines


def build(app: object) -> dict[str, object]:
    """Снять дерево окна и цвета всех картинок (тех же, что в README)."""
    from map_overlay import __version__
    from tools.make_screenshots import build_showcase, collect_shots, prepare_app

    prepare_app(app)  # type: ignore[arg-type]
    window = build_showcase(app)  # type: ignore[arg-type]
    try:
        # Дерево снимается до снимков: последний снимок — мини-версия, и она меняет окно.
        tree = window_tree(window, __version__)
        shots = collect_shots(window, app)  # type: ignore[arg-type]
        mini_tree = window_tree(window, __version__)
    finally:
        window.close()
    data: dict[str, object] = {"tree": tree, "mini_tree": mini_tree, "shots": {}}
    shots_data: dict[str, dict[str, object]] = {}
    for name, pixmap in shots.items():
        key = name.removesuffix(".png").removeprefix("screenshot-")
        shots_data[key] = {
            "size": [pixmap.width(), pixmap.height()],
            "palette": palette(pixmap),
            "colors": theme_colors(pixmap),
        }
    data["shots"] = shots_data
    return data


def compare(expected: dict[str, object], actual: dict[str, object]) -> list[str]:
    """Отличия фактического снимка от эталона — списком понятных строк."""
    problems = _tree_diff("интерфейс", expected.get("tree"), actual.get("tree"))
    problems += _tree_diff("мини-режим", expected.get("mini_tree"), actual.get("mini_tree"))
    expected_shots = expected.get("shots") or {}
    actual_shots = actual.get("shots") or {}
    if not isinstance(expected_shots, dict) or not isinstance(actual_shots, dict):
        return problems
    for key in sorted(set(expected_shots) | set(actual_shots)):
        if key not in actual_shots:
            problems.append(f"{key}: снимка нет")
            continue
        if key not in expected_shots:
            problems.append(f"{key}: снимка нет в эталоне")
            continue
        want, got = expected_shots[key], actual_shots[key]
        if want.get("size") != got.get("size"):
            problems.append(f"{key}: размер {got.get('size')} вместо {want.get('size')}")
        problems.extend(_palette_diffs(key, want.get("palette") or [], got.get("palette") or []))
        problems.extend(_color_diffs(key, want.get("colors") or {}, got.get("colors") or {}))
    return problems


def _tree_diff(title: str, expected: object, actual: object) -> list[str]:
    """Что пропало и что появилось в дереве виджетов."""
    want = [str(line) for line in expected] if isinstance(expected, list) else []
    got = [str(line) for line in actual] if isinstance(actual, list) else []
    if want == got:
        return []
    missing = [line for line in want if line not in got]
    extra = [line for line in got if line not in want]
    problems: list[str] = []
    if missing:
        problems.append(f"{title}: пропало — {missing[:5]}")
    if extra:
        problems.append(f"{title}: появилось — {extra[:5]}")
    if not missing and not extra:
        problems.append(f"{title}: порядок виджетов изменился")
    return problems


def _palette_diffs(
    key: str, expected: list[list[int]], actual: list[list[int]], *, limit: int = 24
) -> list[str]:
    """Клетки, где средний цвет уехал больше чем на ``limit`` по любому каналу."""
    if len(expected) != len(actual):
        return [f"{key}: в эталоне {len(expected)} клеток, снято {len(actual)}"]
    off = [
        f"клетка {index}: {tuple(got)} вместо {tuple(want)}"
        for index, (want, got) in enumerate(zip(expected, actual, strict=True))
        if any(abs(a - b) > limit for a, b in zip(want, got, strict=True))
    ]
    return [f"{key}: цвет уехал — {off[:3]} ({len(off)} клеток)"] if off else []


def _color_diffs(key: str, expected: object, actual: object) -> list[str]:
    """Пропавшие и появившиеся цвета темы: доли сравниваются по наличию, а не по размеру.

    Доля цвета текста зависит от шрифта машины (на раннере она вдвое меньше, чем локально),
    поэтому «сколько» не сравнивается: важно, что цвет темы никуда не делся и новый не
    появился. Плоские области при этом всё равно дают долю в проценты, так что исчезнувший
    акцент или фон виден.
    """
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return [f"{key}: цвета в эталоне испорчены"]
    problems: list[str] = []
    missing = sorted(
        color
        for color, share in expected.items()
        if share >= COLOR_SHARE and actual.get(color, 0.0) < COLOR_PRESENT
    )
    if missing:
        problems.append(f"{key}: цветов темы больше нет — {missing[:4]}")
    added = sorted(
        color
        for color, share in actual.items()
        if share >= COLOR_NEW and expected.get(color, 0.0) < COLOR_PRESENT
    )
    if added:
        problems.append(f"{key}: появились цвета темы — {added[:4]}")
    return problems


def main() -> int:
    """Собрать эталон и записать его в ``tests/goldens/ui.json``."""
    from PySide6.QtWidgets import QApplication

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = str(GOLDEN_SCALE)
    app = QApplication([sys.argv[0]])
    data = build(app)
    GOLDENS.parent.mkdir(parents=True, exist_ok=True)
    GOLDENS.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    shots = data["shots"]
    count = len(shots) if isinstance(shots, dict) else 0
    print(f"{GOLDENS.relative_to(ROOT)}: {count} снимков, {GOLDENS.stat().st_size} байт")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
