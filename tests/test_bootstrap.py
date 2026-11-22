"""Тесты лаунчера: поиск Python, коды выхода и защита от молчаливого закрытия."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import bootstrap  # noqa: E402


def test_parse_args_defaults() -> None:
    args = bootstrap.parse_args([])
    assert args.check_only is False
    assert args.reinstall is False
    assert args.python is None


def test_find_python_accepts_explicit_interpreter() -> None:
    found = bootstrap.find_python(sys.executable)
    assert found is not None
    command, version = found
    assert command == sys.executable
    assert version >= bootstrap.ABSOLUTE_MIN_PYTHON


def test_find_python_rejects_missing_executable() -> None:
    assert bootstrap.find_python("definitely-not-a-python") is None


def test_venv_python_points_inside_venv() -> None:
    path = bootstrap.venv_python()
    assert path.parent.parent == bootstrap.VENV_DIR or path.parent == bootstrap.VENV_DIR / "Scripts"


def test_main_reports_missing_python(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bootstrap, "find_python", lambda _explicit: None)
    code = bootstrap.main([])
    output = capsys.readouterr().out
    assert code == bootstrap.EXIT_PYTHON
    assert "Python" in output
    assert str(bootstrap.LOG_FILE) in output


def test_main_check_only_skips_installation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bootstrap, "find_python", lambda _explicit: (sys.executable, (3, 12)))
    monkeypatch.setattr(bootstrap, "create_venv", lambda _python, _reinstall: True)
    monkeypatch.setattr(bootstrap, "install_dependencies", lambda: True)
    code = bootstrap.main(["--check-only"])
    assert code == bootstrap.EXIT_OK
    assert "Окружение готово" in capsys.readouterr().out


def test_main_stops_when_venv_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bootstrap, "find_python", lambda _explicit: (sys.executable, (3, 12)))
    monkeypatch.setattr(bootstrap, "create_venv", lambda _python, _reinstall: False)
    code = bootstrap.main([])
    assert code == bootstrap.EXIT_VENV
    assert "виртуальное окружение" in capsys.readouterr().out.lower()


def test_main_stops_when_dependencies_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "find_python", lambda _explicit: (sys.executable, (3, 12)))
    monkeypatch.setattr(bootstrap, "create_venv", lambda _python, _reinstall: True)
    monkeypatch.setattr(bootstrap, "install_dependencies", lambda: False)
    assert bootstrap.main([]) == bootstrap.EXIT_DEPS


def test_launcher_never_claims_success_without_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap, "LOG_DIR", tmp_path)

    class DeadProcess:
        returncode = 1

        def poll(self) -> int:
            return 1

    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: DeadProcess())
    assert bootstrap.launch(timeout=0.5) is False
