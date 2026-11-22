from __future__ import annotations

import pytest
from lsp_overlay.domain.errors import JumpTooLargeError
from lsp_overlay.domain.pose import Pose
from lsp_overlay.domain.safety import (
    ANGLE_TOLERANCE,
    LENGTH_TOLERANCE,
    ensure_within_limit,
    translation_distance,
    values_match,
)


def test_translation_distance_ignores_angles() -> None:
    first = Pose(x=0.0, y=0.0, z=0.0, rz=0.0)
    second = Pose(x=3.0, y=4.0, z=0.0, rz=90.0)
    assert translation_distance(first, second) == pytest.approx(5.0)


def test_small_jump_passes() -> None:
    ensure_within_limit(Pose(), Pose(x=1.0, y=1.0), 20.0)


def test_large_jump_is_rejected_with_helpful_message() -> None:
    with pytest.raises(JumpTooLargeError, match="Считать"):
        ensure_within_limit(Pose(), Pose(z=500.0), 20.0)


def test_zero_limit_disables_check() -> None:
    ensure_within_limit(Pose(), Pose(x=10_000.0), 0.0)


def test_values_match_uses_length_tolerance() -> None:
    assert values_match(250.5, 250.5 + LENGTH_TOLERANCE / 2, angle=False)
    assert not values_match(250.5, 250.5 + LENGTH_TOLERANCE * 10, angle=False)


def test_values_match_uses_angle_tolerance() -> None:
    assert values_match(127.42, 127.42 + ANGLE_TOLERANCE / 2, angle=True)
    assert not values_match(127.42, 127.42 + 1.0, angle=True)
