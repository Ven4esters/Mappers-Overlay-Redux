"""Длительности фаз шага: где именно уходит время.

Зачем это нужно. Журнал писал «начал» и «готово», но по нему не видно, что тормозит шаг:
панель отвечает медленно, буфер обмена жуёт вставку или оверлей сам держит паузу между
полями. Поэтому фазы шага замеряются по отдельности, а за сессию по каждой считается
`p95` — не среднее, которое прячет выбросы, и не максимум, который шумит от одного сбоя.

Замеры копятся в памяти (:data:`METRICS`) и пишутся в ``logs/metrics.json`` при выходе:
так ``--check-only`` может показать сводку последней сессии, когда сама сессия уже закрыта.

Запуск вне интерфейса (для тестов и разбора журнала)::

    from map_overlay.application.metrics import METRICS
    print(METRICS.summary())
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Фазы шага в порядке показа. «Итого» — весь шаг целиком: по нему видно, сколько добавили
#: остальные фазы, а сколько съели паузы, которые никуда не отнесены.
PHASES: Final[tuple[str, ...]] = ("чтение", "сверка", "запись", "итого")

MIN_SAMPLES_FOR_P95: Final = 3
#: По одному-двум замерам p95 — это максимум; чтобы честно показывать его, нужно три шага.


@dataclass(frozen=True, slots=True)
class PhaseStats:
    """Сводка одной фазы: сколько раз мерили, типичное время и хвост."""

    count: int
    median_ms: float
    p95_ms: float
    max_ms: float

    def line(self, name: str) -> str:
        """Строка для журнала: фаза, число замеров, медиана, p95, максимум."""
        tail = "p95" if self.count >= MIN_SAMPLES_FOR_P95 else "p95 (мало замеров)"
        return (
            f"{name}: {self.count}× · медиана {self.median_ms:.0f} мс · "
            f"{tail} {self.p95_ms:.0f} мс · максимум {self.max_ms:.0f} мс"
        )


def percentile(values: Iterable[float], share: float) -> float:
    """Ближайший ранг: ``share = 0.95`` — значение, которое не превышают 95 % замеров.

    Ближайший ранг выбран намеренно: интерполяция пригородила бы «среднее двух соседей»,
    которого ни в одном шаге не было, а для ответа «сколько ждать» нужен реальный замер.

    Raises:
        ValueError: если список пуст или доля вне (0, 1].
    """
    ordered = sorted(values)
    if not ordered:
        raise ValueError("нет замеров")
    if not 0.0 < share <= 1.0:
        raise ValueError(f"доля должна быть в (0, 1], получено {share}")
    index = max(0, min(len(ordered) - 1, int(-(-len(ordered) * share // 1)) - 1))
    return ordered[index]


class StepMetrics:
    """Копилка замеров фаз: потокобезопасна, потому что пишет рабочий поток."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: dict[str, list[float]] = {phase: [] for phase in PHASES}

    def record(self, phase: str, elapsed_ms: float) -> None:
        """Запомнить замер фазы. Неизвестная фаза тоже принимается — журнал не должен падать."""
        with self._lock:
            self._samples.setdefault(phase, []).append(elapsed_ms)

    @property
    def steps(self) -> int:
        """Сколько шагов замерено за сессию: каждый шаг даёт один замер «итого»."""
        with self._lock:
            return len(self._samples["итого"])

    def stats(self) -> dict[str, PhaseStats]:
        """Сводка по каждой фазе, где есть замеры."""
        with self._lock:
            samples = {phase: list(values) for phase, values in self._samples.items()}
        result: dict[str, PhaseStats] = {}
        for phase, values in samples.items():
            if not values:
                continue
            result[phase] = PhaseStats(
                count=len(values),
                median_ms=percentile(values, 0.5),
                p95_ms=percentile(values, 0.95),
                max_ms=max(values),
            )
        return result

    def summary(self) -> str:
        """Сводка одной строкой на фазу; пустая сессия — понятная фраза."""
        stats = self.stats()
        if not stats:
            return "шагов не было: замеров нет"
        ordered = [phase for phase in PHASES if phase in stats]
        ordered += sorted(set(stats) - set(PHASES))
        return " · ".join(stats[phase].line(phase) for phase in ordered)

    def slowest(self) -> str:
        """Самая долгая фаза по p95 — ответ на вопрос «что тормозит»."""
        stats = {phase: item for phase, item in self.stats().items() if phase != "итого"}
        if not stats:
            return ""
        phase = max(stats, key=lambda name: stats[name].p95_ms)
        return f"{phase} ({stats[phase].p95_ms:.0f} мс по p95)"

    def reset(self) -> None:
        """Начать новую сессию замеров."""
        with self._lock:
            self._samples = {phase: [] for phase in PHASES}

    def dump(self) -> dict[str, object]:
        """Словарь для файла: сводка и число шагов."""
        return {
            "steps": self.steps,
            "phases": {
                phase: {
                    "count": item.count,
                    "median_ms": round(item.median_ms, 1),
                    "p95_ms": round(item.p95_ms, 1),
                    "max_ms": round(item.max_ms, 1),
                }
                for phase, item in self.stats().items()
            },
        }

    def save(self, path: Path) -> bool:
        """Записать сводку в файл. Ошибка записи не должна мешать закрытию окна.

        Returns:
            ``True``, если файл записан.
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.dump(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Не удалось записать сводку замеров %s: %s", path, exc)
            return False
        return True


METRICS: Final = StepMetrics()
#: Одна копилка на процесс: фазы замеряются в рабочем потоке, читает их интерфейс.


def load_summary(path: Path) -> str:
    """Сводка из файла последней сессии — для ``--check-only``.

    Returns:
        Строку с фазами или пустую строку, если файла нет или он испорчен.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(raw, dict):
        return ""
    phases = raw.get("phases")
    if not isinstance(phases, dict) or not phases:
        return ""
    parts: list[str] = []
    steps = raw.get("steps")
    if isinstance(steps, int):
        parts.append(f"шагов: {steps}")
    for name in [phase for phase in PHASES if phase in phases] + sorted(set(phases) - set(PHASES)):
        item = phases[name]
        if not isinstance(item, dict):
            continue
        count = item.get("count")
        median = item.get("median_ms")
        p95 = item.get("p95_ms")
        if not isinstance(count, int) or not isinstance(median, int | float):
            continue
        p95_text = f"p95 {p95:.0f} мс" if isinstance(p95, int | float) else "p95 —"
        parts.append(f"{name}: {count}× · медиана {median:.0f} мс · {p95_text}")
    return " · ".join(parts)
