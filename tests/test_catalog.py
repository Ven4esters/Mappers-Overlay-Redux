"""Каталог предметов: габариты, поиск по названию и хранение в файле."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lsp_overlay.domain.catalog import Catalog, Dimension, ObjectSpec
from lsp_overlay.domain.errors import ValidationError
from lsp_overlay.infrastructure.catalog_store import CatalogStore

FENCE = ObjectSpec(name="Забор бетонный", length=4.5, width=0.25, thickness=1.2)
BARRIER = ObjectSpec(name="Барьер", length=2.0, width=0.5, thickness=0.9)


def test_object_spec_validates_name_and_dimensions() -> None:
    with pytest.raises(ValidationError):
        ObjectSpec(name="   ")
    with pytest.raises(ValidationError):
        ObjectSpec(name="Стена", length=-1.0)
    with pytest.raises(ValidationError):
        ObjectSpec(name="Стена", width=float("nan"))
    with pytest.raises(ValidationError):
        ObjectSpec(name="Стена", thickness=1000.0)


def test_object_spec_trims_name_and_answers_by_dimension() -> None:
    spec = ObjectSpec(name="  Забор  ", length=4.5, width=0.25, thickness=1.2)
    assert spec.name == "Забор"
    assert spec.dimension(Dimension.LENGTH) == pytest.approx(4.5)
    assert spec.dimension(Dimension.WIDTH) == pytest.approx(0.25)
    assert spec.dimension(Dimension.THICKNESS) == pytest.approx(1.2)
    assert spec.is_complete


def test_object_spec_with_dimension_keeps_other_values() -> None:
    spec = FENCE.with_dimension(Dimension.THICKNESS, 1.5)
    assert spec.thickness == pytest.approx(1.5)
    assert spec.length == pytest.approx(FENCE.length)
    assert not ObjectSpec(name="Панель", length=1.0).is_complete


def test_catalog_upsert_replaces_same_name_ignoring_case() -> None:
    catalog = Catalog().upsert(FENCE).upsert(BARRIER)
    assert len(catalog.objects) == 2
    updated = catalog.upsert(ObjectSpec(name="забор бетонный", length=5.0))
    assert len(updated.objects) == 2
    assert updated.get("ЗАБОР БЕТОННЫЙ") is not None
    assert updated.get("Забор бетонный").length == pytest.approx(5.0)  # type: ignore[union-attr]


def test_catalog_search_is_case_insensitive_and_sorted() -> None:
    catalog = Catalog().upsert(FENCE).upsert(BARRIER)
    assert [spec.name for spec in catalog.find("заб")] == ["Забор бетонный"]
    assert [spec.name for spec in catalog.find("")] == ["Барьер", "Забор бетонный"]
    assert catalog.find("нет такого") == ()


def test_catalog_remove_missing_name_is_not_error() -> None:
    catalog = Catalog().upsert(FENCE)
    assert catalog.remove("забора нет").objects == catalog.objects
    assert catalog.remove("Забор бетонный").is_empty


def test_catalog_json_roundtrip_skips_broken_records() -> None:
    catalog = Catalog().upsert(FENCE).upsert(BARRIER)
    restored = Catalog.from_dict(catalog.to_dict())
    assert restored.objects == catalog.objects
    partial = Catalog.from_dict({"version": 1, "objects": [FENCE.to_dict(), {"name": ""}, 42]})
    assert [spec.name for spec in partial.objects] == ["Забор бетонный"]
    with pytest.raises(ValidationError):
        Catalog.from_dict({"objects": "нет"})


def test_store_saves_and_loads(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "objects.json")
    assert store.load().is_empty
    store.save(Catalog().upsert(FENCE))
    assert store.path.exists()
    assert store.load().objects == (FENCE,)


def test_store_quarantines_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "objects.json"
    path.write_text("{ не json", encoding="utf-8")
    store = CatalogStore(path)
    assert store.load().is_empty
    assert (tmp_path / "objects.broken.json").exists()


def test_store_json_is_readable_and_utf8(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "objects.json")
    store.save(Catalog().upsert(FENCE))
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["objects"][0]["name"] == "Забор бетонный"


def test_dimensions_are_length_width_and_thickness() -> None:
    assert [dimension.value for dimension in Dimension] == ["length", "width", "thickness"]
    assert [dimension.label for dimension in Dimension] == ["Длина", "Ширина", "Толщина"]
    assert [dimension.short for dimension in Dimension] == ["Д", "Ш", "Т"]


def test_old_height_record_is_read_as_thickness() -> None:
    spec = ObjectSpec.from_dict({"name": "Стена", "length": 4.0, "width": 0.2, "height": 0.15})
    assert spec.thickness == pytest.approx(0.15)
    assert spec.to_dict()["thickness"] == pytest.approx(0.15)
    assert "height" not in spec.to_dict()


def test_catalog_file_with_height_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "objects.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "objects": [
                    {"name": "Забор", "length": 4.5, "width": 0.25, "height": 1.2},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    spec = CatalogStore(path).load().get("Забор")
    assert spec is not None
    assert spec.thickness == pytest.approx(1.2)
    assert spec.is_complete
