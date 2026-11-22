"""Проверки запуска, логирования и хранилища настроек."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from lsp_overlay.app import EXIT_ENVIRONMENT, EXIT_OK, _check, main, parse_args
from lsp_overlay.config import ConfigError, Settings
from lsp_overlay.infrastructure.config_store import CONFIG_ENV, ConfigStore, default_config_path
from lsp_overlay.infrastructure.win32_input import Win32InputBackend
from lsp_overlay.logging_setup import LOG_FILE_NAME, setup_logging

from fakes import build_calibration


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.debug is False
    assert args.check is False


def test_check_reports_missing_calibration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    code = _check(Settings(), store)
    output = capsys.readouterr().out
    assert code == EXIT_ENVIRONMENT
    assert "калибровка не завершена" in output


def test_check_passes_with_full_calibration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Win32InputBackend, "is_ready", lambda self: True)
    settings = replace(Settings(), calibration=build_calibration())
    code = _check(settings, ConfigStore(tmp_path / "settings.json"))
    output = capsys.readouterr().out
    assert code == EXIT_OK
    assert "Окружение готово" in output


def test_main_check_returns_environment_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / "settings.json"))
    assert main(["--check", "--log-dir", str(tmp_path / "logs")]) == EXIT_ENVIRONMENT


def test_logging_writes_json_lines(tmp_path: Path) -> None:
    import logging

    log_path = setup_logging(tmp_path)
    logging.getLogger("test").info("привет")
    assert log_path.name == LOG_FILE_NAME
    payload = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["message"] == "привет"
    assert payload["level"] == "INFO"


def test_config_store_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "nested" / "settings.json")
    settings = replace(Settings(step=0.25), calibration=build_calibration())
    store.save(settings)
    assert store.load() == settings


def test_config_store_missing_file_gives_defaults(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "absent.json")
    assert store.load() == Settings()


def test_config_store_quarantines_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ это не json", encoding="utf-8")
    store = ConfigStore(path)
    assert store.load() == Settings()
    assert (tmp_path / "settings.broken.json").exists()


def test_config_store_rejects_invalid_values(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"step": -5}), encoding="utf-8")
    assert ConfigStore(path).load() == Settings()


def test_saving_invalid_settings_raises(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    with pytest.raises(ConfigError):
        store.save(Settings(step=0.0))


def test_config_path_can_be_overridden(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / "custom.json"))
    assert default_config_path() == tmp_path / "custom.json"
