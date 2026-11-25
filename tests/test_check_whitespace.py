"""Гигиена текстовых файлов: хвостовые пробелы и перевод строки в конце."""

from __future__ import annotations

from pathlib import Path

from tools.check_whitespace import check_file, check_text, main


def test_trailing_space_is_reported() -> None:
    problems = check_text("строка \n", path="a.py", allow_trailing=False)
    assert [problem.message for problem in problems] == ["пробел в конце строки"]


def test_missing_final_newline_is_reported() -> None:
    problems = check_text("без перевода", path="a.py", allow_trailing=False)
    assert any("в конце файла" in problem.message for problem in problems)


def test_markdown_may_have_hard_break() -> None:
    assert check_text("строка  \nдальше\n", path="a.md", allow_trailing=True) == []


def test_clean_text_passes() -> None:
    assert check_text("строка\n", path="a.py", allow_trailing=False) == []


def test_binary_file_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(b"\x89PNG\r\n")
    assert check_file(path) == []


def test_main_reports_problem(tmp_path: Path, capsys) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("хвост \n", encoding="utf-8")
    assert main([str(path)]) == 1
    assert "пробел в конце строки" in capsys.readouterr().out


def test_main_passes_on_clean_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("чисто\n", encoding="utf-8")
    assert main([str(path)]) == 0
