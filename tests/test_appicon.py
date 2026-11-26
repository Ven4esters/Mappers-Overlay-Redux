"""Иконка приложения: рисунок, файлы для exe и подключение к окну."""

from __future__ import annotations

import struct
import tomllib
from pathlib import Path

from map_overlay.ui.appicon import CANVAS, SIZES, icon, pixmap, png_bytes
from PySide6.QtWidgets import QApplication
from tools.make_icons import build_ico, read_ico

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "map_overlay" / "data" / "app.ico"
PREVIEW = ROOT / "docs" / "app-icon.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_size(data: bytes) -> tuple[int, int]:
    """Ширина и высота из заголовка IHDR."""
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_icon_has_every_size(qt_app: QApplication) -> None:
    """QIcon отдаёт кадр для любого запрошенного размера."""
    result = icon()
    assert not result.isNull()
    for size in SIZES:
        assert not result.pixmap(size, size).isNull()


def test_drawing_has_background_and_center(qt_app: QApplication) -> None:
    """Иконка нарисована, а не пустая: есть и фон по краю, и сердцевина в центре."""
    image = pixmap(64).toImage()
    assert image.pixelColor(32, 32).alpha() > 0
    assert image.pixelColor(0, 0).alpha() == 0  # прозрачные поля за скруглением
    corner = image.pixelColor(10, 10)
    assert corner.alpha() > 0  # внутри скруглённого квадрата — фон
    center = image.pixelColor(32, 32)
    assert center.blue() > center.red()  # сердцевина акцентного цвета


def test_png_bytes_are_png(qt_app: QApplication) -> None:
    data = png_bytes(64)
    assert data.startswith(PNG_SIGNATURE)
    assert _png_size(data) == (64, 64)


def test_ico_file_has_every_size() -> None:
    frames = read_ico(ICO.read_bytes())
    assert [width for width, _, _ in frames] == list(SIZES)


def test_each_ico_frame_is_a_png_of_the_right_size() -> None:
    data = ICO.read_bytes()
    _, _, count = struct.unpack_from("<HHH", data, 0)
    offset = 6 + 16 * count
    for width, height, length in read_ico(data):
        frame = data[offset : offset + length]
        assert frame.startswith(PNG_SIGNATURE)
        assert _png_size(frame) == (width, height)
        offset += length


def test_build_ico_round_trip(qt_app: QApplication) -> None:
    """Сборка .ico из кадров читается обратно теми же размерами."""
    images = {size: png_bytes(size) for size in SIZES}
    frames = read_ico(build_ico(images))
    assert [width for width, _, _ in frames] == list(SIZES)


def test_preview_png_exists_and_is_square() -> None:
    assert PREVIEW.is_file()
    assert _png_size(PREVIEW.read_bytes()) == (256, 256)


def test_spec_embeds_icon() -> None:
    spec = (ROOT / "MappersOverlayRedux.spec").read_text(encoding="utf-8")
    assert "app.ico" in spec
    assert "icon=str(ICON)" in spec
    assert "tools.make_icons" in spec


def test_wheel_ships_icon() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["map_overlay"]
    assert "data/*.ico" in patterns


def test_icon_files_are_present() -> None:
    """Иконки лежат в репозитории: без них exe соберётся без значка."""
    assert ICO.is_file() and ICO.stat().st_size > 1000
    assert CANVAS == 256
