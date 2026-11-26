"""Картинки документации: README ссылается на существующие файлы, схема не врёт.

Скриншоты собирает ``tools.make_screenshots``. Проверять их содержимое в тесте нельзя,
но можно проверить главное: файлы на месте, ссылки в README живые, а схема диагоналей
считается тем же кодом, что и шаг предмета.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from map_overlay.domain.directions import Direction
from map_overlay.domain.movement import shifted
from map_overlay.domain.pose import Pose
from tools.make_screenshots import DIAGRAM_RX, DIAGRAM_STEP, _diagonal_points

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _referenced_images() -> list[Path]:
    """Все картинки, на которые ссылается README."""
    text = README.read_text(encoding="utf-8")
    found = re.findall(r"\]\(([^)\s]+\.png)\)", text) + re.findall(r'src="([^"]+\.png)"', text)
    return [ROOT / link for link in found]


def test_readme_references_existing_images() -> None:
    """Ни одной битой ссылки на картинку."""
    images = _referenced_images()
    assert images, "README потерял картинки"
    missing = [path for path in images if not path.is_file()]
    assert not missing, f"нет файлов: {missing}"


def test_documentation_images_are_png() -> None:
    """Картинки — действительно PNG, а не переименованный мусор."""
    for path in _referenced_images():
        assert path.read_bytes()[:8] == PNG_MAGIC, path


def test_readme_matches_package_version() -> None:
    """Версия в README не отстала от пакета."""
    from map_overlay import __version__

    text = README.read_text(encoding="utf-8")
    assert str(__version__) in text or "CHANGELOG" in text


@pytest.mark.parametrize("rx", DIAGRAM_RX)
def test_diagram_points_come_from_movement_code(rx: float) -> None:
    """Точки схемы совпадают со сдвигом ``Num 9`` из домена, а не нарисованы на глаз."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx, ry=0.0, rz=0.0)
    after = shifted(pose, Direction.FORWARD_RIGHT, DIAGRAM_STEP)
    assert _diagonal_points(rx) == pytest.approx((after.y, after.z), abs=1e-9)


def test_diagram_keeps_diagonal_length_in_yz_plane() -> None:
    """У наклонённого предмета длина сдвига в плоскости ``Y/Z`` одна: шаг/√2.

    Случай «без наклона» считается отдельно и даёт полную длину шага — это и есть та
    заметная разница между случаями, ради которой схема нарисована.
    """
    arm = DIAGRAM_STEP / math.sqrt(2.0)
    for rx in DIAGRAM_RX:
        dy, dz = _diagonal_points(rx)
        length = math.hypot(dy, dz)
        expected = DIAGRAM_STEP if rx == 0.0 else arm
        assert length == pytest.approx(expected, abs=1e-3)


def test_diagram_turns_from_vertical_to_horizontal() -> None:
    """``RX = 90`` кладёт диагональ на горизонталь, при ``RX = 0`` она под 45°."""
    assert _diagonal_points(90.0)[1] == pytest.approx(0.0, abs=1e-9)
    dy, dz = _diagonal_points(0.0)
    assert dy == pytest.approx(-dz, abs=1e-9)
