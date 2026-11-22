"""Сверка с первой версией 2.0 (коммит ``d2db3d0``): шаг должен совпадать до знака.

Эталон снят прогоном ``lsp_overlay.domain.movement.move`` из той версии и лежит в
``tests/first_release_steps.json``. Тест держит умолчания приложения на месте: любое
изменение осей, наклонов или формулы сдвига сразу его ломает.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lsp_overlay.config import Settings
from lsp_overlay.domain.directions import DiagonalMode, Direction
from lsp_overlay.domain.movement import move
from lsp_overlay.domain.pose import Pose

GOLDEN = Path(__file__).with_name("first_release_steps.json")
START = Pose(x=10.0, y=-20.0, z=5.0)


def load_rows() -> list[dict[str, float | str]]:
    """Эталонные шаги первой версии."""
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_table_is_complete() -> None:
    rows = load_rows()
    assert len(rows) == len(Direction) * 12 * 3 * 2


@pytest.mark.parametrize(
    "row",
    load_rows(),
    ids=lambda row: f"{row['direction']}-{row['rz']}-{row['step']}-{row['mode']}",
)
def test_step_matches_the_first_release(row: dict[str, float | str]) -> None:
    """Шаг по умолчанию повторяет первую версию до последнего знака."""
    settings = Settings()
    pose = Pose(
        x=START.x,
        y=START.y,
        z=START.z,
        rx=float(row["rx"]),
        ry=float(row["ry"]),
        rz=float(row["rz"]),
    )
    result = move(
        pose,
        Direction(str(row["direction"])),
        float(row["step"]),
        diagonal_mode=DiagonalMode(str(row["mode"])),
        use_tilt=settings.use_tilt,
        frame=settings.move_frame,
    )
    assert (result.x - pose.x, result.y - pose.y, result.z - pose.z) == pytest.approx(
        (row["dx"], row["dy"], row["dz"]), abs=1e-12
    )
