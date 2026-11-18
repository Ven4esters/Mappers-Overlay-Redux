"""Module 3 tests: capture geometry with a mocked mss (no real screens needed).
Модуль 3: геометрия захвата на замоканном mss (реальные экраны не нужны)."""

from __future__ import annotations

import pytest

from app import capture
from app.capture import CaptureError, Region, capture_fullscreen, capture_region, image_to_bytes, normalize_region


class FakeShot:
    def __init__(self, size: tuple[int, int]):
        self.size = size
        self.bgra = bytes(size[0] * size[1] * 4)


UNION = {"left": -100, "top": 0, "width": 300, "height": 200}  # e.g. 2 monitors with negative origin


class FakeSct:
    def __init__(self) -> None:
        self.monitors = [UNION, {"left": 0, "top": 0, "width": 200, "height": 200}]

    def __enter__(self) -> "FakeSct":
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def grab(self, target) -> FakeShot:
        return FakeShot((int(target["width"]), int(target["height"])))


@pytest.fixture(autouse=True)
def mock_mss(monkeypatch):
    monkeypatch.setattr(capture, "_mss", lambda: FakeSct())


def test_normalize_region_swaps_corners() -> None:
    region = normalize_region(120, 90, 20, 10)
    assert (region.left, region.top, region.width, region.height) == (20, 10, 100, 80)


def test_normalize_region_minimum_size() -> None:
    region = normalize_region(5, 5, 5, 5)
    assert region.width == 1 and region.height == 1


def test_virtual_union_and_fullscreen() -> None:
    assert capture.virtual_union() == Region(-100, 0, 300, 200)
    shot = capture_fullscreen()
    assert shot.size == (300, 200)


def test_capture_region_negative_origin_offset() -> None:
    shot = capture_region(Region(10, 10, 50, 50))
    assert shot.size == (50, 50)  # offset must be 10 - (-100) = 110 inside the union


def test_capture_region_dpr_scaling() -> None:
    shot = capture_region(Region(10, 10, 50, 50), dpr=2.0)
    assert shot.size == (100, 100)


def test_capture_region_out_of_bounds_raises() -> None:
    with pytest.raises(CaptureError):
        capture_region(Region(10_000, 10_000, 50, 50))


def test_region_partially_offscreen_is_clamped() -> None:
    shot = capture_region(Region(-150, 0, 100, 100))  # spans -150..-50, union starts at -100
    assert shot.size == (50, 100)  # only the visible half survives, clamped to the union


def test_image_to_bytes_png_signature() -> None:
    from PIL import Image

    payload = image_to_bytes(Image.new("RGB", (8, 8), (12, 34, 56)), "PNG")
    assert payload.startswith(b"\x89PNG")
    payload_jpg = image_to_bytes(Image.new("RGB", (8, 8)), "JPEG", quality=80)
    assert payload_jpg.startswith(b"\xff\xd8")


def test_hotkeys_module_imports() -> None:
    import app.hotkeys as hotkeys

    assert hasattr(hotkeys, "HotkeyManager")
    assert isinstance(hotkeys.HotkeyManager.supported(), bool)
