"""Ядро предметной области: чистая математика без Qt и Win32.

Модули слоя не знают ни про интерфейс, ни про ввод, ни про файлы.
"""

from lsp_overlay.domain.directions import DiagonalMode, Direction
from lsp_overlay.domain.errors import DomainError, JumpTooLargeError
from lsp_overlay.domain.geometry import Vec3, rotation_matrix, transform, wrap_angle
from lsp_overlay.domain.measure import MeasureSlot, MeasureTape, Span
from lsp_overlay.domain.movement import move, rotate
from lsp_overlay.domain.pose import Axis, Pose

__all__ = [
    "Axis",
    "DiagonalMode",
    "Direction",
    "DomainError",
    "JumpTooLargeError",
    "MeasureSlot",
    "MeasureTape",
    "Pose",
    "Span",
    "Vec3",
    "move",
    "rotate",
    "rotation_matrix",
    "transform",
    "wrap_angle",
]
