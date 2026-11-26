"""Проверка окружения без запуска окна."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from map_overlay.main import APP_NAME, main
from map_overlay.paths import HOME_ENV, LEGACY_HOME_ENV, application_dir


def test_check_only_prints_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    assert main(["--check-only"]) == 0
    output = capsys.readouterr().out
    assert "Mapper's Overlay Redux" in output
    assert "Калибровка: 0/6" in output
    assert (tmp_path / "logs" / "overlay.log").exists()


def test_check_only_reports_single_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """В --check-only видно, занят ли замок: это объясняет «второй не запускается»."""
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    monkeypatch.setattr("map_overlay.main.is_busy", lambda: True)
    assert main(["--check-only"]) == 0
    assert "Экземпляр: уже запущен — второй не стартует" in capsys.readouterr().out


def test_check_only_reports_free_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    monkeypatch.setattr("map_overlay.main.is_busy", lambda: False)
    assert main(["--check-only"]) == 0
    assert "Экземпляр: не запущен" in capsys.readouterr().out


def test_check_only_counts_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    payload = {
        "schema_version": 1,
        "calibration": {"x": {"x": 10, "y": 20}, "y": {"x": 30, "y": 20}},
    }
    (config_dir / "settings.json").write_text(json.dumps(payload), encoding="utf-8")
    assert main(["--check-only"]) == 0
    assert "Калибровка: 2/6" in capsys.readouterr().out


def test_check_only_reports_broken_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text("{сломано", encoding="utf-8")
    assert main(["--check-only"]) == 2
    assert "не читаются" in capsys.readouterr().out


def test_startup_error_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from map_overlay import main as main_module
    from map_overlay.errors import UnsupportedPlatformError

    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))

    def broken() -> int:
        raise UnsupportedPlatformError("клики доступны только в Windows")

    monkeypatch.setattr(main_module, "_run_window", broken)
    assert main([]) == 1
    assert "только в Windows" in capsys.readouterr().err


def test_check_only_reports_sizes_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    payload = {
        "schema_version": 1,
        "active": "Ящик",
        "items": [{"name": "Ящик", "length": 2.0, "width": 1.0}],
    }
    (config_dir / "sizes.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert main(["--check-only"]) == 0
    output = capsys.readouterr().out
    assert "Размеры предметов: 1" in output
    assert "выбран «Ящик»" in output


def test_check_only_reports_broken_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sizes.json").write_text("{сломано", encoding="utf-8")
    assert main(["--check-only"]) == 2
    assert "Размеры предметов не читаются" in capsys.readouterr().out


def test_application_name_is_mappers_overlay() -> None:
    """Название приложения — «Mapper's Overlay Redux» (переименовано в 1.12.0)."""
    assert APP_NAME == "Mapper's Overlay Redux"


def test_home_environment_variable_renamed_with_legacy_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Новое имя переменной работает, старое тоже читается — профили не ломаются."""
    assert HOME_ENV == "MAPPERS_OVERLAY_HOME"
    assert LEGACY_HOME_ENV == "MAP_OVERLAY_HOME"
    new_dir = tmp_path / "новый"
    old_dir = tmp_path / "старый"
    monkeypatch.setenv(HOME_ENV, str(new_dir))
    assert application_dir() == new_dir.resolve()
    monkeypatch.delenv(HOME_ENV)
    monkeypatch.setenv(LEGACY_HOME_ENV, str(old_dir))
    assert application_dir() == old_dir.resolve()
    monkeypatch.setenv(HOME_ENV, str(new_dir))
    assert application_dir() == new_dir.resolve()
