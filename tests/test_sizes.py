"""Библиотека размеров: проверка предметов, выбор и файл."""

from __future__ import annotations

import math

import pytest
from map_overlay.domain.sizes import (
    MAX_ITEMS,
    MAX_NAME_LEN,
    MAX_SIZE_M,
    SIZE_USES,
    ObjectSize,
    SizeLibrary,
    SizeUse,
)
from map_overlay.errors import ConfigError, ValidationError

CRATE = ObjectSize(name="Ящик", length=2.0, width=1.0)
PALLET = ObjectSize(name="Паллета", length=1.2, width=0.8)


def _item(name: str, length: float = 2.0, width: float = 1.0) -> ObjectSize:
    """Предмет для проверок правки: название и габариты по умолчанию."""
    return ObjectSize(name=name, length=length, width=width)


def _library(*items: ObjectSize, active: str | None = None) -> SizeLibrary:
    """Библиотека из предметов с необязательным выбранным."""
    library = SizeLibrary()
    for item in items:
        library = library.with_item(item)
    return library if active is None else library.select(active)


def test_name_is_stripped() -> None:
    assert ObjectSize(name="  Ящик  ", length=1.0, width=1.0).name == "Ящик"


def test_empty_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="пустым"):
        ObjectSize(name="   ", length=1.0, width=1.0)


def test_long_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match=str(MAX_NAME_LEN)):
        ObjectSize(name="я" * (MAX_NAME_LEN + 1), length=1.0, width=1.0)


@pytest.mark.parametrize("value", [0.0, -1.0, MAX_SIZE_M + 1, math.inf, math.nan])
def test_bad_length_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        ObjectSize(name="Ящик", length=value, width=1.0)


def test_bad_width_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Ширина"):
        ObjectSize(name="Ящик", length=1.0, width=0.0)


def test_halves() -> None:
    assert CRATE.half_length == pytest.approx(1.0)
    assert CRATE.half_width == pytest.approx(0.5)


def test_text_for_interface() -> None:
    assert CRATE.text() == "Ящик · 2 × 1 м"


@pytest.mark.parametrize(
    ("use", "expected"),
    [
        (SizeUse.LENGTH, 2.0),
        (SizeUse.WIDTH, 1.0),
        (SizeUse.HALF_LENGTH, 1.0),
        (SizeUse.HALF_WIDTH, 0.5),
    ],
)
def test_size_use_values(use: SizeUse, expected: float) -> None:
    assert use.value_for(CRATE) == pytest.approx(expected)


def test_every_use_has_title_and_hint() -> None:
    for use in SIZE_USES:
        assert use.label
        assert use.hint
    assert [use.label for use in SIZE_USES] == ["Длина", "Ширина", "½ длины", "½ ширины"]


def test_add_item_keeps_order() -> None:
    library = SizeLibrary().with_item(CRATE).with_item(PALLET)
    assert [item.name for item in library.items] == ["Ящик", "Паллета"]


def test_first_item_becomes_active() -> None:
    assert SizeLibrary().with_item(CRATE).active == "Ящик"


def test_second_item_does_not_change_active() -> None:
    assert SizeLibrary().with_item(CRATE).with_item(PALLET).active == "Ящик"


def test_same_name_replaces_item() -> None:
    library = (
        SizeLibrary().with_item(CRATE).with_item(ObjectSize(name="ящик", length=3.0, width=2.0))
    )
    assert len(library.items) == 1
    assert library.items[0].length == pytest.approx(3.0)


def test_replacing_active_item_keeps_it_active() -> None:
    library = SizeLibrary().with_item(CRATE).select("Ящик")
    changed = library.with_item(ObjectSize(name="ЯЩИК", length=4.0, width=1.0))
    assert changed.active == "ЯЩИК"
    assert changed.active_item is not None
    assert changed.active_item.length == pytest.approx(4.0)


def test_library_limit() -> None:
    items = tuple(
        ObjectSize(name=f"Предмет {index}", length=1.0, width=1.0) for index in range(MAX_ITEMS)
    )
    library = SizeLibrary(items=items)
    with pytest.raises(ValidationError, match=str(MAX_ITEMS)):
        library.with_item(ObjectSize(name="Лишний", length=1.0, width=1.0))


def test_remove_item_clears_active() -> None:
    library = SizeLibrary().with_item(CRATE).select("Ящик")
    assert library.without("Ящик").active is None


def test_remove_unknown_item_changes_nothing() -> None:
    library = SizeLibrary().with_item(CRATE)
    assert library.without("Нет такого") is library


def test_select_unknown_item_is_rejected() -> None:
    with pytest.raises(ValidationError, match="нет в библиотеке"):
        SizeLibrary().with_item(CRATE).select("Паллета")


def test_select_none_clears() -> None:
    library = SizeLibrary().with_item(CRATE).select("Ящик")
    assert library.select(None).active is None


def test_select_finds_by_case_insensitive_name() -> None:
    library = SizeLibrary().with_item(CRATE).select("ящик")
    assert library.active == "Ящик"


def test_duplicate_names_are_rejected() -> None:
    with pytest.raises(ConfigError, match="дважды"):
        SizeLibrary(items=(CRATE, ObjectSize(name="ящик", length=1.0, width=1.0)))


def test_unknown_active_is_rejected() -> None:
    with pytest.raises(ConfigError, match="отсутствует"):
        SizeLibrary(items=(CRATE,), active="Паллета")


def test_dict_roundtrip() -> None:
    library = SizeLibrary().with_item(CRATE).with_item(PALLET).select("Паллета")
    restored = SizeLibrary.from_dict(library.to_dict())
    assert restored == library


def test_from_dict_without_items_is_empty() -> None:
    assert SizeLibrary.from_dict({"schema_version": 1}) == SizeLibrary()


def test_from_dict_rejects_newer_schema() -> None:
    with pytest.raises(ConfigError, match="новее"):
        SizeLibrary.from_dict({"schema_version": 2, "items": []})


def test_from_dict_rejects_bad_structure() -> None:
    with pytest.raises(ConfigError, match="список"):
        SizeLibrary.from_dict({"items": "ящик"})


def test_from_dict_rejects_bad_item() -> None:
    with pytest.raises(ConfigError, match="должно быть числом"):
        SizeLibrary.from_dict({"items": [{"name": "Ящик", "length": True, "width": 1.0}]})


def test_from_dict_wraps_size_validation() -> None:
    with pytest.raises(ConfigError, match="Библиотека размеров испорчена"):
        SizeLibrary.from_dict({"items": [{"name": "Ящик", "length": 0.0, "width": 1.0}]})


def test_from_dict_rejects_duplicates() -> None:
    entries = [
        {"name": "Ящик", "length": 1.0, "width": 1.0},
        {"name": "ящик", "length": 2.0, "width": 2.0},
    ]
    with pytest.raises(ConfigError, match="дважды"):
        SizeLibrary.from_dict({"items": entries})


def test_replace_renames_item_and_keeps_order() -> None:
    library = _library(_item("Ящик"), _item("Паллета"), _item("Бочка"))
    updated = library.replace("Паллета", _item("Паллета EU", 1.2, 0.8))
    assert [item.name for item in updated.items] == ["Ящик", "Паллета EU", "Бочка"]
    assert updated.find("Паллета EU") == ObjectSize("Паллета EU", 1.2, 0.8)


def test_replace_changes_only_sizes() -> None:
    library = _library(_item("Ящик"), active="Ящик")
    updated = library.replace("Ящик", _item("ящик", 3.0, 1.5))
    assert [item.name for item in updated.items] == ["ящик"]
    assert updated.active == "ящик"
    assert updated.find("Ящик") == ObjectSize("ящик", 3.0, 1.5)


def test_replace_keeps_active_item_under_new_name() -> None:
    library = _library(_item("Ящик"), _item("Бочка"), active="Ящик")
    updated = library.replace("Ящик", _item("Ящик XL", 3.0, 2.0))
    assert updated.active == "Ящик XL"
    assert updated.active_item == ObjectSize("Ящик XL", 3.0, 2.0)


def test_replace_other_item_does_not_touch_active() -> None:
    library = _library(_item("Ящик"), _item("Бочка"), active="Бочка")
    updated = library.replace("Ящик", _item("Ящик XL"))
    assert updated.active == "Бочка"


def test_replace_rejects_name_taken_by_another_item() -> None:
    library = _library(_item("Ящик"), _item("Бочка"))
    with pytest.raises(ConfigError):
        library.replace("Ящик", _item("Бочка"))


def test_replace_rejects_unknown_item() -> None:
    library = _library(_item("Ящик"))
    with pytest.raises(ValidationError):
        library.replace("Стол", _item("Стол"))
