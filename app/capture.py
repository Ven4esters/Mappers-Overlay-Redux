"""Screen capture core — no Qt dependencies (unit-testable).
Ядро захвата экрана — без зависимостей от Qt (покрыто юнит-тестами).

Coordinates are physical pixels in "virtual desktop" space (the union of all
monitors), matching what ``mss`` reports. Qt logical coordinates must be
scaled by the primary screen's devicePixelRatio before being passed here —
the overlay widget does that for you.
Координаты — физические пиксели в виртуальном десктопе (объединение мониторов),
как у ``mss``. Qt-логические координаты умножайте на DPR экрана.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import BinaryIO, Literal, Optional

from PIL import Image


class CaptureError(RuntimeError):
    """Base capture failure. / Базовая ошибка захвата."""


class UnsupportedPlatformError(CaptureError):
    """Feature not supported on this OS. / Функция не поддерживается на этой ОС."""


@dataclass(frozen=True)
class Region:
    """Axis-aligned rectangle in virtual-desktop pixels. / Прямоугольник области."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def as_mss(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def normalize_region(x1: int, y1: int, x2: int, y2: int) -> Region:
    """Build a Region from two corners, swapping if needed. / Нормализовать две угловые точки."""
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    return Region(left, top, max(1, right - left), max(1, bottom - top))


def _mss():
    import mss  # local import keeps non-capture tests/light usage lean

    return mss.mss()


def virtual_union() -> Region:
    """Union of all monitors. / Объединение всех мониторов."""
    with _mss() as sct:
        monitor = sct.monitors[0]  # index 0 is the union; 1..N are individual screens
        return Region(int(monitor["left"]), int(monitor["top"]), int(monitor["width"]), int(monitor["height"]))


def grab(region: Optional[Region] = None) -> Image.Image:
    """Grab pixels; ``None`` means the whole virtual desktop. / Снимок области (или всех экранов)."""
    with _mss() as sct:
        target = region.as_mss() if region is not None else sct.monitors[0]
        try:
            shot = sct.grab(target)
        except Exception as exc:  # mss raises its own ScreenShotError
            raise CaptureError(f"mss failed to grab {target}: {exc}") from exc
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def capture_fullscreen() -> Image.Image:
    """Everything, everywhere, all at once (all monitors). / Все мониторы разом."""
    return grab()


def _windows_foreground_rect() -> Optional[Region]:
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:  # minimised windows report garbage
        return None
    return Region(rect.left, rect.top, width, height)


def capture_active_window() -> Image.Image:
    """Foreground window (Windows). / Снимок активного окна (Windows)."""
    rect = _windows_foreground_rect()
    if rect is None:
        if sys.platform.startswith("win"):
            raise CaptureError("Could not determine the foreground window / Не удалось определить активное окно")
        raise UnsupportedPlatformError(
            "Active-window capture works on Windows only (Linux/macOS need tools like xdotool) / "
            "Захват активного окна поддерживается только на Windows"
        )
    union = virtual_union()
    left, top = max(union.left, rect.left), max(union.top, rect.top)
    right, bottom = min(union.right, rect.right), min(union.bottom, rect.bottom)
    if right - left < 1 or bottom - top < 1:
        raise CaptureError("Foreground window is outside the virtual screen / Окно вне видимой области")
    return grab(Region(left, top, right - left, bottom - top))


def capture_region(region: Region, *, dpr: float = 1.0) -> Image.Image:
    """Crop ``region`` (logical Qt coords) from the desktop, scaling by ``dpr``.
    Вырезать область (логические координаты Qt) из десктопа с учётом DPR."""
    if dpr <= 0:
        dpr = 1.0
    union = virtual_union()
    physical = Region(int(region.left * dpr), int(region.top * dpr),
                      int(region.width * dpr), int(region.height * dpr))
    shot = grab(union)
    box = (max(0, physical.left - union.left), max(0, physical.top - union.top),
           min(shot.width, physical.left - union.left + physical.width),
           min(shot.height, physical.top - union.top + physical.height))
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        raise CaptureError("Region lies outside the virtual screen / Область вне видимой области")
    return shot.crop(box)


def image_to_bytes(image: Image.Image, fmt: Literal["PNG", "JPEG"] = "PNG", quality: int = 92) -> bytes:
    """Encode an image to bytes. / Закодировать изображение в байты."""
    import io

    buffer = io.BytesIO()
    if fmt.upper() == "JPEG":
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=max(1, min(100, quality)), optimize=True)
    else:
        image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
