"""Проверки, которые не дают «улететь» пропу.

Решение из предыдущей версии, которое себя оправдало: любой ввод сверяется с
реальным состоянием игры, а один шаг не может увести предмет слишком далеко.
"""

from __future__ import annotations

import math

from lsp_overlay.domain.errors import JumpTooLargeError
from lsp_overlay.domain.pose import Pose

DEFAULT_MAX_JUMP = 20.0
LENGTH_TOLERANCE = 0.002
ANGLE_TOLERANCE = 0.05


def translation_distance(origin: Pose, target: Pose) -> float:
    """Расстояние между позициями двух поз в метрах."""
    return math.dist(origin.position, target.position)


def ensure_within_limit(previous: Pose, target: Pose, max_jump: float) -> None:
    """Бросает :class:`JumpTooLargeError`, если шаг больше лимита.

    ``max_jump <= 0`` отключает проверку — это осознанный «режим эксперта».
    """
    if max_jump <= 0.0:
        return
    distance = translation_distance(previous, target)
    if distance > max_jump:
        raise JumpTooLargeError(distance, max_jump)


def values_match(expected: float, actual: float, *, angle: bool) -> bool:
    """Совпадает ли прочитанное из игры значение с ожидаемым (с допуском)."""
    tolerance = ANGLE_TOLERANCE if angle else LENGTH_TOLERANCE
    return abs(expected - actual) <= tolerance
