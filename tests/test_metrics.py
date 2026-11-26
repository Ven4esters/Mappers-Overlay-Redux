"""Сводка фаз шага: процентили, тексты и файл последней сессии.

Зачем отдельные тесты. Цифры в журнале читает человек, решая «что тормозит», поэтому
проверяется не только арифметика, но и то, что p95 не выдаёт максимум за «типичный
хвост» на паре замеров и что пустая сессия говорит об этом словами, а не пустой строкой.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from map_overlay.application.metrics import (
    MIN_SAMPLES_FOR_P95,
    PHASES,
    StepMetrics,
    load_summary,
    percentile,
)


def test_percentile_is_a_real_measurement() -> None:
    """Ближайший ранг: p95 не выдумывает значение между замерами."""
    values = list(range(1, 101))
    assert percentile(values, 1.0) == 100
    assert percentile(values, 0.5) == 50
    assert percentile(values, 0.95) == 95
    assert percentile([7.0], 0.95) == 7.0


def test_percentile_rejects_empty_and_wrong_share() -> None:
    """Нет замеров — нечего считать; доля вне (0, 1] — ошибка вызывающего."""
    with pytest.raises(ValueError, match="нет замеров"):
        percentile([], 0.95)
    with pytest.raises(ValueError, match="доля"):
        percentile([1.0], 0.0)


def test_stats_count_median_and_tail() -> None:
    """Сводка фазы: сколько замеров, медиана, p95 и максимум."""
    metrics = StepMetrics()
    for value in (10.0, 20.0, 30.0, 40.0, 1000.0):
        metrics.record("запись", value)
    stats = metrics.stats()["запись"]
    assert stats.count == 5
    assert stats.median_ms == 30.0
    assert stats.p95_ms == 1000.0
    assert stats.max_ms == 1000.0


def test_steps_count_total_phases() -> None:
    """Число шагов — это число замеров «итого»: один шаг — один замер."""
    metrics = StepMetrics()
    assert metrics.steps == 0
    metrics.record("итого", 300.0)
    metrics.record("итого", 420.0)
    metrics.record("запись", 200.0)
    assert metrics.steps == 2


def test_summary_names_every_phase() -> None:
    """Строка сводки перечисляет фазы по порядку и отмечает малое число замеров."""
    metrics = StepMetrics()
    metrics.record("чтение", 120.0)
    metrics.record("запись", 300.0)
    summary = metrics.summary()
    assert "чтение" in summary
    assert "запись" in summary
    assert "мало замеров" in summary


def test_summary_of_empty_session_says_so() -> None:
    """Пустая сессия — понятная фраза: пустая строка выглядела бы как сбой."""
    assert StepMetrics().summary() == "шагов не было: замеров нет"
    assert StepMetrics().slowest() == ""


def test_slowest_phase_ignores_the_total() -> None:
    """«Что тормозит» — самая долгая фаза, а не весь шаг: иначе ответ всегда «итого»."""
    metrics = StepMetrics()
    for _ in range(MIN_SAMPLES_FOR_P95):
        metrics.record("сверка", 50.0)
        metrics.record("запись", 400.0)
        metrics.record("итого", 900.0)
    assert metrics.slowest() == "запись (400 мс по p95)"


def test_unknown_phase_does_not_break_the_journal() -> None:
    """Незнакомая фаза попадает в сводку последней: терять замер хуже, чем показать его."""
    metrics = StepMetrics()
    metrics.record("пауза", 15.0)
    assert "пауза" in metrics.summary()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Файл сводки читается обратно: по нему ``--check-only`` показывает прошлую сессию."""
    metrics = StepMetrics()
    for value in (100.0, 200.0, 300.0):
        metrics.record("итого", value)
        metrics.record("запись", value / 2)
    path = tmp_path / "logs" / "metrics.json"
    assert metrics.save(path) is True
    summary = load_summary(path)
    assert "шагов: 3" in summary
    assert "запись" in summary
    assert "p95" in summary


def test_save_creates_missing_folder(tmp_path: Path) -> None:
    """Папки журналов может не быть: сохранение сводки создаёт её само."""
    path = tmp_path / "logs" / "nested" / "metrics.json"
    assert StepMetrics().save(path) is True
    assert path.is_file()


def test_save_failure_is_not_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Не записалось — предупреждение в журнал, а не падение при закрытии окна."""
    path = tmp_path / "logs" / "metrics.json"

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("диск переполнен")

    monkeypatch.setattr(Path, "mkdir", explode)
    assert StepMetrics().save(path) is False


@pytest.mark.parametrize(
    "payload", ["не json", "[]", "{}", '{"phases": {}}', '{"phases": {"итого": 5}}']
)
def test_load_summary_survives_broken_file(tmp_path: Path, payload: str) -> None:
    """Испорченный файл — пустая сводка, а не исключение в ``--check-only``."""
    path = tmp_path / "metrics.json"
    path.write_text(payload, encoding="utf-8")
    assert load_summary(path) == ""


def test_load_summary_without_file(tmp_path: Path) -> None:
    """Файла нет (первый запуск) — сводки нет."""
    assert load_summary(tmp_path / "нет-такого.json") == ""


def test_dump_is_json_serialisable() -> None:
    """Сводка целиком уходит в JSON: без NaN и объектов, которые не сериализуются."""
    metrics = StepMetrics()
    metrics.record("итого", 512.0)
    metrics.record("запись", 301.0)
    text = json.dumps(metrics.dump(), allow_nan=False, ensure_ascii=False)
    assert "итого" in text
    assert not math.isnan(metrics.dump()["phases"]["итого"]["p95_ms"])  # type: ignore[index]


def test_phases_are_named_in_report_order() -> None:
    """Порядок фаз задан один раз: по нему строится и журнал, и ``--check-only``."""
    assert PHASES[0] == "чтение"
    assert PHASES[-1] == "итого"
