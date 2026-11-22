from __future__ import annotations

import math

import pytest
from lsp_overlay.domain.geometry import (
    add_scaled,
    length,
    normalize_diagonal,
    rotation_matrix,
    transform,
    wrap_angle,
)


def test_identity_matrix_keeps_local_axes_equal_to_world() -> None:
    matrix = rotation_matrix()
    assert transform((1.0, 0.0, 0.0), matrix) == pytest.approx((1.0, 0.0, 0.0))
    assert transform((0.0, 1.0, 0.0), matrix) == pytest.approx((0.0, 1.0, 0.0))
    assert transform((0.0, 0.0, 1.0), matrix) == pytest.approx((0.0, 0.0, 1.0))


def test_yaw_90_turns_forward_to_west() -> None:
    matrix = rotation_matrix(rz_degrees=90.0)
    assert transform((0.0, 1.0, 0.0), matrix) == pytest.approx((-1.0, 0.0, 0.0), abs=1e-12)


def test_yaw_90_turns_right_to_north() -> None:
    matrix = rotation_matrix(rz_degrees=90.0)
    assert transform((1.0, 0.0, 0.0), matrix) == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)


def test_yaw_negative_90_turns_forward_to_east() -> None:
    matrix = rotation_matrix(rz_degrees=-90.0)
    assert transform((0.0, 1.0, 0.0), matrix) == pytest.approx((1.0, 0.0, 0.0), abs=1e-12)


def test_pitch_90_lifts_forward_up() -> None:
    matrix = rotation_matrix(rx_degrees=90.0)
    assert transform((0.0, 1.0, 0.0), matrix) == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)


def test_roll_90_lifts_right_up() -> None:
    matrix = rotation_matrix(ry_degrees=90.0)
    assert transform((1.0, 0.0, 0.0), matrix) == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)


def test_matrix_is_orthonormal_for_random_angles() -> None:
    matrix = rotation_matrix(37.5, -12.0, 127.42)
    for row in matrix:
        assert sum(component * component for component in row) == pytest.approx(1.0)
    first, second = matrix[0], matrix[1]
    assert sum(a * b for a, b in zip(first, second, strict=True)) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, 0.0),
        (180.0, -180.0),
        (-180.0, -180.0),
        (190.0, -170.0),
        (-190.0, 170.0),
        (540.0, -180.0),
    ],
)
def test_wrap_angle(raw: float, expected: float) -> None:
    assert wrap_angle(raw) == pytest.approx(expected)


def test_wrap_angle_has_no_negative_zero() -> None:
    assert math.copysign(1.0, wrap_angle(-360.0)) > 0


def test_wrap_angle_rejects_infinity() -> None:
    with pytest.raises(ValueError, match="конечным"):
        wrap_angle(float("inf"))


def test_normalize_diagonal_keeps_length() -> None:
    vector = normalize_diagonal((1.0, 1.0, 0.0))
    assert vector == pytest.approx((math.sqrt(0.5), math.sqrt(0.5), 0.0))
    assert length(vector) == pytest.approx(1.0)


def test_normalize_diagonal_of_zero_vector_is_safe() -> None:
    assert normalize_diagonal((0.0, 0.0, 1.0)) == (0.0, 0.0, 1.0)


def test_add_scaled_moves_along_vector() -> None:
    assert add_scaled((1.0, 2.0, 3.0), (0.0, 1.0, 0.0), 5.0) == pytest.approx((1.0, 7.0, 3.0))
