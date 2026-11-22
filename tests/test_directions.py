"""Направления: восемь сторон и знаки осей по правилам пользователя."""

from __future__ import annotations

import pytest
from map_overlay.domain.directions import Direction

EXPECTED_AXES = {
    Direction.FORWARD: (1, 0),
    Direction.BACK: (-1, 0),
    Direction.LEFT: (0, 1),
    Direction.RIGHT: (0, -1),
    Direction.FORWARD_LEFT: (1, 1),
    Direction.FORWARD_RIGHT: (1, -1),
    Direction.BACK_LEFT: (-1, 1),
    Direction.BACK_RIGHT: (-1, -1),
}


@pytest.mark.parametrize(("direction", "axes"), EXPECTED_AXES.items())
def test_axes_follow_user_rules(direction: Direction, axes: tuple[int, int]) -> None:
    assert direction.axes == axes


def test_there_are_exactly_eight_directions() -> None:
    assert len(Direction) == 8
    assert set(EXPECTED_AXES) == set(Direction)


def test_diagonals_change_both_axes() -> None:
    for direction in Direction:
        if direction.is_diagonal:
            assert all(axis != 0 for axis in direction.axes)
        else:
            assert 0 in direction.axes


def test_titles_and_glyphs_are_unique() -> None:
    titles = {direction.label for direction in Direction}
    glyphs = {direction.glyph for direction in Direction}
    assert len(titles) == 8
    assert len(glyphs) == 8


def test_forward_is_x_plus_and_left_is_y_plus() -> None:
    assert Direction.FORWARD.axes[0] == 1
    assert Direction.LEFT.axes[1] == 1
    assert Direction.BACK.axes[0] == -1
    assert Direction.RIGHT.axes[1] == -1
