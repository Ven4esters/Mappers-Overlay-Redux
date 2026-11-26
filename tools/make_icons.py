"""Собрать файлы иконки приложения из рисунка в коде.

Иконка рисуется `map_overlay/ui/appicon.py`, а этот скрипт сохраняет её там, где
её ждут система и документация:

* `map_overlay/data/app.ico` — многоразмерный значок для `.exe` (его указывает
  `MappersOverlayRedux.spec` в параметре ``icon``);
* `docs/app-icon.png` — крупный PNG для README и документации.

Запуск::

    python -m tools.make_icons

Файлы детерминированные: при изменении рисунка их нужно пересобрать и закоммитить,
иначе exe получит старую иконку.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from map_overlay.console import use_utf8_console
from map_overlay.ui.appicon import SIZES, pixmap, png_bytes
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
ICO_PATH = ROOT / "map_overlay" / "data" / "app.ico"
PREVIEW_PATH = ROOT / "docs" / "app-icon.png"
PREVIEW_SIZE = 256
ICO_PLANES = 1
ICO_BIT_DEPTH = 32
ICO_HEADER = 6
ICO_ENTRY = 16


def build_ico(images: dict[int, bytes]) -> bytes:
    """Собрать .ico из PNG-кадров: заголовок, каталог, затем сами PNG."""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    directory = b""
    payload = b""
    offset = ICO_HEADER + ICO_ENTRY * count
    for size in sorted(images):
        data = images[size]
        # Ширина и высота в каталоге — один байт: 256 записывается как 0.
        directory += struct.pack(
            "<BBBBHHII",
            size % 256,
            size % 256,
            0,
            0,
            ICO_PLANES,
            ICO_BIT_DEPTH,
            len(data),
            offset + len(payload),
        )
        payload += data
    return header + directory + payload


def read_ico(data: bytes) -> list[tuple[int, int, int]]:
    """Прочитать каталог .ico: список (ширина, высота, размер кадра)."""
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1:
        raise ValueError("это не .ico")
    frames = []
    for index in range(count):
        width, height, _, _, _, _, length, _ = struct.unpack_from(
            "<BBBBHHII", data, ICO_HEADER + index * ICO_ENTRY
        )
        frames.append((width or 256, height or 256, length))
    return frames


def main() -> int:
    """Точка входа: печать в UTF-8, чтобы кириллица не роняла запуск."""
    use_utf8_console()
    """Собрать иконки и записать их в репозиторий."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    del app
    images = {size: png_bytes(size) for size in SIZES}
    data = build_ico(images)
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICO_PATH.write_bytes(data)
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    pixmap(PREVIEW_SIZE).save(str(PREVIEW_PATH), "PNG")
    frames = read_ico(data)
    print(f"{ICO_PATH.relative_to(ROOT)}: {len(frames)} кадров, {len(data)} байт")
    print("  размеры:", ", ".join(f"{width}x{height}" for width, height, _ in frames))
    print(f"{PREVIEW_PATH.relative_to(ROOT)}: {PREVIEW_SIZE}x{PREVIEW_SIZE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
