"""Политика исключений: просроченное или необоснованное исключение ломает CI."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tools.check_exceptions import (
    COLUMNS,
    collect_problems,
    main,
    parse_rows,
    split_row,
)

TODAY = date(2026, 11, 19)


def _file(rows: list[str]) -> str:
    header = "| " + " | ".join(COLUMNS) + " |"
    separator = "|" + "|".join("---" for _ in COLUMNS) + "|"
    return "\n".join([header, separator, *rows]) + "\n"


def _write(tmp_path: Path, rows: list[str]) -> None:
    path = tmp_path / "docs" / "quality"
    path.mkdir(parents=True)
    (path / "exceptions.md").write_text(_file(rows), encoding="utf-8")


def test_split_row_strips_pipes() -> None:
    assert split_row("| a | b |") == ("a", "b")


def test_valid_active_exception_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ["| PLR0913 | конструкторы | внедрение зависимостей | @owner | 2027-01-31 | активно |"],
    )
    assert collect_problems(tmp_path, today=TODAY) == []


def test_missing_file_is_reported(tmp_path: Path) -> None:
    assert collect_problems(tmp_path, today=TODAY)


def test_expired_exception_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ["| PLR0913 | конструкторы | внедрение | @owner | 2026-01-01 | активно |"],
    )
    problems = collect_problems(tmp_path, today=TODAY)
    assert problems and "просрочено" in problems[0]


def test_owner_must_be_a_handle(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ["| PLR0913 | конструкторы | внедрение | Иван | 2027-01-31 | активно |"],
    )
    problems = collect_problems(tmp_path, today=TODAY)
    assert any("@имя" in problem for problem in problems)


def test_unknown_status_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ["| PLR0913 | конструкторы | внедрение | @owner | 2027-01-31 | когда-нибудь |"],
    )
    problems = collect_problems(tmp_path, today=TODAY)
    assert any("статус" in problem for problem in problems)


def test_empty_reason_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, ["| PLR0913 | конструкторы |  | @owner | 2027-01-31 | активно |"])
    problems = collect_problems(tmp_path, today=TODAY)
    assert any("Причина" in problem for problem in problems)


def test_parse_skips_header_and_separator() -> None:
    rows = parse_rows(_file(["| PLR0913 | где | почему | @owner | 2027-01-31 | активно |"]))
    assert len(rows) == 1


def test_main_counts_active_exceptions(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path,
        ["| PLR0913 | конструкторы | внедрение | @owner | 2027-01-31 | активно |"],
    )
    assert main([], root=tmp_path, today=TODAY) == 0
    assert "активных: 1" in capsys.readouterr().out
