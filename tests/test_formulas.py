"""Таблица эталонов движения собирается из кода и сверяется в check_docs."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from tools.check_docs import check_formulas
from tools.make_formulas import (
    BLOCK_END,
    BLOCK_START,
    CASES,
    TARGET,
    Case,
    Key,
    main,
    mismatches,
    render,
    replace_block,
    stale,
)


@pytest.fixture(name="formulas")
def formulas_fixture(tmp_path: Path) -> Path:
    """Копия настоящего FORMATS.md во временной папке: правим копию, не репозиторий."""
    root = Path(__file__).resolve().parent.parent
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    shutil.copyfile(root / TARGET, target)
    return tmp_path


def test_render_has_all_reference_cases() -> None:
    """В таблице каждый эталон заказчика — ни один не потерялся при генерации."""
    block = render()
    assert BLOCK_START in block and BLOCK_END in block
    for number in range(1, len(CASES) + 1):
        assert f"\n{number}. " in block
    assert block.count("Num ") >= len(CASES)


def test_code_matches_customer_references() -> None:
    """Код движения сходится с эталонами: расхождений нет."""
    assert mismatches() == []


def test_changed_code_reports_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если подменить ожидание эталона, генератор это заметит, а не перепишет молча."""
    broken = replace(
        CASES[0],
        keys=(Key(CASES[0].keys[0].direction, point=(-1.0, -1.0, -1.0)),),
    )
    problems = mismatches([broken])
    assert problems and "Num 9" in problems[0]


def test_committed_table_is_current() -> None:
    """В репозитории лежит ровно та таблица, что собирается из кода."""
    assert not stale()


def test_stale_is_detected(formulas: Path) -> None:
    """Подменённое число в таблице — это «устарела», а не «нормально»."""
    target = formulas / TARGET
    target.write_text(
        target.read_text(encoding="utf-8").replace("−1848.204", "−1848.999", 1), encoding="utf-8"
    )
    assert stale(formulas)


def test_main_rewrites_stale_table(formulas: Path) -> None:
    """Одна команда возвращает таблицу к виду из кода."""
    target = formulas / TARGET
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("−1848.204", "−1848.999", 1), encoding="utf-8")
    assert main([], root=formulas) == 0
    assert not stale(formulas)
    assert target.read_text(encoding="utf-8") == text


def test_main_check_reports_stale(formulas: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--check`` не пишет файл, а говорит, что делать."""
    target = formulas / TARGET
    edited = target.read_text(encoding="utf-8").replace("шаг 3.0, Num 9:", "шаг 3.5, Num 9:", 1)
    target.write_text(edited, encoding="utf-8")
    assert main(["--check"], root=formulas) == 1
    assert target.read_text(encoding="utf-8") == edited
    assert "make_formulas" in capsys.readouterr().out


def test_replace_block_needs_markers() -> None:
    """Без маркеров писать некуда: это ошибка, а не повод дописать в конец."""
    with pytest.raises(SystemExit):
        replace_block("без маркеров", render())


def test_check_formulas_passes_on_repository() -> None:
    """check_docs не видит проблем в нынешней таблице."""
    assert check_formulas() == []


def test_check_formulas_finds_stale_table(formulas: Path) -> None:
    """check_docs падает на таблице, которая разошлась с кодом."""
    target = formulas / TARGET
    target.write_text(
        target.read_text(encoding="utf-8").replace("+1.738", "+1.739", 1), encoding="utf-8"
    )
    problems = check_formulas(formulas)
    assert len(problems) == 1
    assert "устарела" in problems[0].message


def test_check_formulas_requires_file(tmp_path: Path) -> None:
    """Нет файла — нет таблицы: это проблема, а не тишина."""
    problems = check_formulas(tmp_path)
    assert problems and "нет файла" in problems[0].message


def test_blocks_are_identical_after_two_runs(formulas: Path) -> None:
    """Генерация идемпотентна: второй запуск ничего не меняет."""
    first = (formulas / TARGET).read_text(encoding="utf-8")
    assert main([], root=formulas) == 0
    second = (formulas / TARGET).read_text(encoding="utf-8")
    assert first == second


def test_two_references_give_only_the_delta() -> None:
    """Эталоны ``Alt`` и трёх углов записаны в игре сдвигом, без точки «стало»."""
    assert all(isinstance(case, Case) and case.keys for case in CASES)
    delta_cases = [case for case in CASES if case.mode == "delta"]
    assert len(delta_cases) == 2
    assert all(key.point is None for case in delta_cases for key in case.keys)
