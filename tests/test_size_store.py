"""Файл библиотеки размеров: чтение, запись и испорченные данные."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from map_overlay.context import AppContext
from map_overlay.domain.pose import Pose
from map_overlay.domain.sizes import ObjectSize, SizeLibrary
from map_overlay.errors import ConfigError
from map_overlay.infrastructure.size_store import JsonSizeStore

CRATE = ObjectSize(name="Ящик", length=2.0, width=1.0)


def test_missing_file_gives_empty_library(tmp_path: Path) -> None:
    assert JsonSizeStore(tmp_path / "config" / "sizes.json").load() == SizeLibrary()


def test_roundtrip(tmp_path: Path) -> None:
    store = JsonSizeStore(tmp_path / "config" / "sizes.json")
    library = SizeLibrary().with_item(CRATE).select("Ящик")
    store.save(library)
    assert store.load() == library


def test_save_creates_directory_and_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "config" / "sizes.json"
    store = JsonSizeStore(path)
    store.save(SizeLibrary().with_item(CRATE))
    assert path.exists()
    assert not path.with_suffix(".tmp").exists()


def test_saved_file_is_readable_json(tmp_path: Path) -> None:
    path = tmp_path / "sizes.json"
    JsonSizeStore(path).save(SizeLibrary().with_item(CRATE))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["items"][0]["name"] == "Ящик"
    assert raw["schema_version"] == 1


def test_broken_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "sizes.json"
    path.write_text("{ не json", encoding="utf-8")
    with pytest.raises(ConfigError, match="Не удалось прочитать"):
        JsonSizeStore(path).load()


def test_bad_structure_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "sizes.json"
    path.write_text(json.dumps({"items": [{"name": 5}]}), encoding="utf-8")
    with pytest.raises(ConfigError):
        JsonSizeStore(path).load()


def test_unwritable_path_is_reported(tmp_path: Path) -> None:
    # Каталог вместо файла: запись обязана дать понятную ошибку, а не упасть.
    path = tmp_path / "sizes.json"
    path.mkdir()
    with pytest.raises(ConfigError, match="Не удалось сохранить"):
        JsonSizeStore(path).save(SizeLibrary().with_item(CRATE))


def test_context_keeps_library_between_runs(tmp_path: Path) -> None:
    """Библиотека переживает перезапуск: её читает следующий AppContext."""
    from fakes import FakeCursor, FakeHotkeySource, FakePanel, FakeStore

    path = tmp_path / "sizes.json"

    def make_context() -> AppContext:
        return AppContext(
            store=FakeStore(),
            cursor=FakeCursor(),
            panel_factory=lambda _settings: FakePanel(Pose(x=0.0, y=0.0, z=0.0)),
            hotkeys=FakeHotkeySource(),
            size_store=JsonSizeStore(path),
        )

    first = make_context()
    first.save_sizes(SizeLibrary().with_item(CRATE))
    second = make_context()
    assert [item.name for item in second.sizes.items] == ["Ящик"]
    assert second.sizes.active == "Ящик"
    assert second.sizes_error is None


def test_context_reports_broken_library_and_keeps_working(tmp_path: Path) -> None:
    from fakes import FakeCursor, FakeHotkeySource, FakePanel, FakeStore

    path = tmp_path / "sizes.json"
    path.write_text("{сломано", encoding="utf-8")
    context = AppContext(
        store=FakeStore(),
        cursor=FakeCursor(),
        panel_factory=lambda _settings: FakePanel(Pose(x=0.0, y=0.0, z=0.0)),
        hotkeys=FakeHotkeySource(),
        size_store=JsonSizeStore(path),
    )
    assert context.sizes.items == ()
    assert context.sizes_error is not None
