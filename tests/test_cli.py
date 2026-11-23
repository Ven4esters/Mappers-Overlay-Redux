"""Проверка окружения без запуска окна."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from map_overlay.main import main


def test_check_only_prints_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAP_OVERLAY_HOME", str(tmp_path))
    assert main(["--check-only"]) == 0
    output = capsys.readouterr().out
    assert "Map Overlay Redux" in output
    assert "Калибровка: 0/6" in output
    assert (tmp_path / "logs" / "overlay.log").exists()


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
