"""Таблица эталонов движения — генерируется из кода, а не пишется руками.

Эталоны заказчика (числа, проверенные в игре) лежат здесь как данные. Скрипт считает
каждый случай настоящим кодом ``map_overlay.domain.movement.shifted`` и сверяет ответ
с эталоном: если код разошёлся с эталоном, скрипт падает и **ничего не пишет**. Если
всё сошлось — он перерисовывает блок в ``docs/FORMULAS.md`` между маркерами.

Так таблица в документации не может «уехать» от кода: её сверяет ``tools.check_docs``
и падает, если блок в файле отличается от свежесобранного.

Запуск: ``python -m tools.make_formulas`` (или ``python -m tools.make_formulas --check``).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from map_overlay.domain.directions import Direction
from map_overlay.domain.movement import shifted
from map_overlay.domain.pose import Pose

ROOT = Path(__file__).resolve().parent.parent
TARGET = Path("docs") / "FORMULAS.md"
BLOCK_START = "<!-- формулы: начало (генерируется tools/make_formulas.py) -->"
BLOCK_END = "<!-- формулы: конец -->"

#: Ключи на цифровой клавиатуре — так их называет заказчик в эталонах.
KEYS: dict[Direction, str] = {
    Direction.FORWARD: "Num 8",
    Direction.BACK: "Num 2",
    Direction.LEFT: "Num 4",
    Direction.RIGHT: "Num 6",
    Direction.FORWARD_LEFT: "Num 7",
    Direction.FORWARD_RIGHT: "Num 9",
    Direction.BACK_LEFT: "Num 1",
    Direction.BACK_RIGHT: "Num 3",
}

MINUS = "\u2212"
TOLERANCE = 0.001  # эталон записан до миллиметра


@dataclass(frozen=True, slots=True)
class Key:
    """Одна клавиша эталона и то, что заказчик увидел в игре.

    Эталон задаёт либо точку «стало», либо сдвиг — то, что записано в игре.
    """

    direction: Direction
    point: tuple[float, float, float] | None = None
    delta: tuple[float, float, float] | None = None
    #: Пояснение перед ключом: «пара 9-1» — так эталон записан в игре.
    note: str = ""


@dataclass(frozen=True, slots=True)
class Case:
    """Эталон заказчика: поза, шаг, клавиши и ожидаемый результат.

    ``mode`` задаёт вид строки в таблице: ``point`` — «было → стало», ``point_delta`` —
    точка и сдвиг, ``delta`` — только сдвиг.
    """

    title: str
    pose: Pose
    step: float
    keys: tuple[Key, ...]
    mode: str = "point"
    #: Нужен ли режим высоты (клавиша ``Alt``).
    tilt: bool = False


def _num(value: float) -> str:
    """Число с тремя знаками и типографским минусом."""
    return f"{value:.3f}".replace("-", MINUS)


def _point(pose: Pose) -> str:
    """Точка в формате заказчика: `(−1849.342, 416.528, 129.816)`."""
    return f"({_num(pose.x)}, {_num(pose.y)}, {_num(pose.z)})"


def _delta(values: Sequence[float]) -> str:
    """Сдвиг в формате заказчика: `Δ = (0, −2.058, +0.513)`."""
    parts = []
    for value in values:
        if value == 0:
            parts.append("0")
            continue
        text = _num(value)
        parts.append(text if text.startswith(MINUS) else "+" + text)
    return f"Δ = ({', '.join(parts)})"


def _moved(case: Case, key: Key) -> Pose:
    """Куда оверлей сдвинет позу этим ключом."""
    return shifted(case.pose, key.direction, case.step, tilt=case.tilt)


def _moved_delta(case: Case, key: Key) -> tuple[float, float, float]:
    """Сдвиг по мировым осям — то, что уйдёт в панель."""
    moved = _moved(case, key)
    return (
        round(moved.x - case.pose.x, 3),
        round(moved.y - case.pose.y, 3),
        round(moved.z - case.pose.z, 3),
    )


def _matches(actual: tuple[float, ...], expected: tuple[float, ...]) -> bool:
    """Сверка с эталоном: разница в пределах миллиметра — то, что видно в игре."""
    return all(abs(a - e) <= TOLERANCE for a, e in zip(actual, expected, strict=True))


def mismatches(cases: Iterable[Case] | None = None) -> list[str]:
    """Расхождения кода с эталонами: пустой список — всё сходится."""
    problems: list[str] = []
    for case in cases if cases is not None else CASES:
        for key in case.keys:
            moved = _moved(case, key)
            name = KEYS[key.direction]
            if key.point is not None and not _matches((moved.x, moved.y, moved.z), key.point):
                problems.append(
                    f"эталон «{case.title}» {name}: код даёт {(moved.x, moved.y, moved.z)},"
                    f" эталон {key.point}"
                )
            if key.delta is not None and not _matches(_moved_delta(case, key), key.delta):
                problems.append(
                    f"эталон «{case.title}» {name}: сдвиг {_moved_delta(case, key)},"
                    f" эталон {key.delta}"
                )
    return problems


def render(cases: Sequence[Case] | None = None) -> str:
    """Собрать блок таблицы целиком (вместе с маркерами)."""
    lines = [BLOCK_START, "```text"]
    for number, case in enumerate(cases if cases is not None else CASES, start=1):
        lines.append(f"{number}. {case.title}")
        if case.mode == "point":
            lines.append(f"   {_point(case.pose)} → {_point(_moved(case, case.keys[0]))}")
        else:
            if case.mode == "point_delta":
                lines.append(f"   {_point(case.pose)}")
            for key in case.keys:
                prefix = f"{key.note}, " if key.note else ""
                head = f"   {prefix}{KEYS[key.direction]} →"
                tail = _delta(_moved_delta(case, key))
                if case.mode == "point_delta":
                    lines.append(f"{head} {_point(_moved(case, key))}   {tail}")
                else:
                    lines.append(f"{head} {tail}")
        lines.append("")
    while lines[-1] == "":
        lines.pop()
    lines.extend(["```", BLOCK_END])
    return "\n".join(lines) + "\n"


def replace_block(text: str, block: str) -> str:
    """Заменить блок между маркерами; маркеров нет — это ошибка, а не повод дописать."""
    start = text.find(BLOCK_START)
    end = text.find(BLOCK_END)
    if start < 0 or end < 0:
        raise SystemExit(f"в {TARGET} нет маркеров таблицы эталонов")
    rest = text[end + len(BLOCK_END) :].lstrip("\n")
    return text[:start] + block + "\n" + rest


def stale(root: Path = ROOT) -> bool:
    """Таблица в файле отличается от свежесобранной (и код сошёлся с эталонами)."""
    text = (root / TARGET).read_text(encoding="utf-8")
    return replace_block(text, render()) != text


def main(argv: Iterable[str] | None = None, *, root: Path = ROOT) -> int:
    """Перерисовать таблицу (``--check`` — только сказать, расходится ли она)."""
    args = list(argv or ())
    problems = mismatches()
    if problems:
        for problem in problems:
            print(problem)
        print("Код разошёлся с эталонами заказчика: таблица не обновлена.")
        return 1
    if "--check" in args:
        if not stale(root):
            print(f"{TARGET}: таблица совпадает с кодом")
            return 0
        print(f"{TARGET}: таблица эталонов устарела — запустите python -m tools.make_formulas")
        return 1
    path = root / TARGET
    text = path.read_text(encoding="utf-8")
    updated = replace_block(text, render())
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        print(f"{TARGET}: таблица обновлена ({len(CASES)} эталонов)")
    else:
        print(f"{TARGET}: таблица уже совпадает с кодом")
    return 0


#: Эталоны заказчика — те же числа, что проверяет `tests/test_movement.py`.
CASES: tuple[Case, ...] = (
    Case(
        title="Без углов, шаг 3.0, Num 9:",
        pose=Pose(x=-1849.342, y=416.528, z=129.816),
        step=3.0,
        keys=(Key(Direction.FORWARD_RIGHT, point=(-1849.342, 414.407, 131.937)),),
    ),
    Case(
        title="Без углов, шаг 3.0, Num 9:",
        pose=Pose(x=-1850.403, y=414.979, z=130.554),
        step=3.0,
        keys=(Key(Direction.FORWARD_RIGHT, point=(-1850.403, 412.858, 132.675)),),
    ),
    Case(
        title="RX = 37°, RY = 0, шаг 2.0, Num 9:",
        pose=Pose(x=-1849.342, y=416.528, z=128.826, rx=37.0),
        step=2.0,
        keys=(Key(Direction.FORWARD_RIGHT, point=(-1849.342, 415.677, 129.955)),),
    ),
    Case(
        title="RX = 55°, RY = 17°, шаг 3.0, Num 9:",
        pose=Pose(x=-1849.342, y=416.528, z=128.826, rx=55.0, ry=17.0),
        step=3.0,
        keys=(Key(Direction.FORWARD_RIGHT, point=(-1848.465, 414.178, 130.472)),),
    ),
    Case(
        title="RX = 41.5°, RY = 22.3°, шаг 3.0, Num 9:",
        pose=Pose(x=-1849.342, y=416.528, z=128.816, rx=41.5, ry=22.3),
        step=3.0,
        keys=(Key(Direction.FORWARD_RIGHT, point=(-1848.204, 414.689, 130.895)),),
    ),
    Case(
        title="Alt, RY = 10°, шаг 3.0, Num 8:",
        pose=Pose(x=0.0, y=0.0, z=0.0, ry=10.0),
        step=3.0,
        keys=(Key(Direction.FORWARD, delta=(0.521, 0.0, 2.954)),),
        mode="delta",
        tilt=True,
    ),
    Case(
        title="RX = 76°, RY = RZ = 0, шаг 3.0, пары 9-1 и 7-3:",
        pose=Pose(x=-1850.403, y=416.221, z=130.544, rx=76.0),
        step=3.0,
        keys=(
            Key(
                Direction.FORWARD_RIGHT,
                point=(-1850.403, 414.163, 131.057),
                delta=(0.0, -2.058, 0.513),
            ),
            Key(
                Direction.BACK_LEFT, point=(-1850.403, 418.279, 130.031), delta=(0.0, 2.058, -0.513)
            ),
            Key(
                Direction.FORWARD_LEFT,
                point=(-1850.403, 416.734, 132.602),
                delta=(0.0, 0.513, 2.058),
            ),
            Key(
                Direction.BACK_RIGHT,
                point=(-1850.403, 415.708, 128.486),
                delta=(0.0, -0.513, -2.058),
            ),
        ),
        mode="point_delta",
    ),
    Case(
        title="RX = 55°, RY = 17°, шаг 3.0, пара 7-3 (RY в формулу не входит):",
        pose=Pose(x=-1849.342, y=416.528, z=128.826, rx=55.0, ry=17.0),
        step=3.0,
        keys=(
            Key(
                Direction.FORWARD_LEFT,
                point=(-1849.342, 417.745, 130.564),
                delta=(0.0, 1.217, 1.738),
            ),
            Key(
                Direction.BACK_RIGHT,
                point=(-1849.342, 415.311, 127.088),
                delta=(0.0, -1.217, -1.738),
            ),
        ),
        mode="point_delta",
    ),
    Case(
        title="RX = 30°, RY = 20°, RZ = 40°, шаг 2.0 (проверка формул трёх углов):",
        pose=Pose(x=0.0, y=0.0, z=0.0, rx=30.0, ry=20.0, rz=40.0),
        step=2.0,
        keys=(
            Key(Direction.FORWARD_RIGHT, delta=(1.128, -0.280, 1.628), note="пара 9-1"),
            Key(Direction.BACK_RIGHT, delta=(0.787, -0.938, -0.707), note="пара 7-3"),
        ),
        mode="delta",
    ),
)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
