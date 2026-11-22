"""Файл настроек: чтение, запись, испорченные данные."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from map_overlay.config import Settings
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point
from map_overlay.errors import ConfigError
from map_overlay.infrastructure.settings_store import JsonSettingsStore


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    store = JsonSettingsStore(tmp_path / "config" / "settings.json")
    assert store.load() == Settings()


def test_saved_settings_are_loaded(tmp_path: Path) -> None:
    path = tmp_path / "config" / "settings.json"
    store = JsonSettingsStore(path)
    settings = Settings().with_point(Field.Y, Point(300, 200))
    store.save(settings)
    assert path.exists()
    assert store.load() == settings
    assert not path.with_suffix(".tmp").exists()


def test_corrupted_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{это не json", encoding="utf-8")
    with pytest.raises(ConfigError, match="прочитать"):
        JsonSettingsStore(path).load()


def test_unknown_schema_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(ConfigError, match="новее приложения"):
        JsonSettingsStore(path).load()


def test_save_failure_is_reported(tmp_path: Path) -> None:
    blocker = tmp_path / "config"
    blocker.write_text("файл вместо папки", encoding="utf-8")
    with pytest.raises(ConfigError, match="сохранить"):
        JsonSettingsStore(blocker / "settings.json").save(Settings())
