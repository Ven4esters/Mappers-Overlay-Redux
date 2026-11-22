"""Шесть полей панели LSP: координаты и углы."""

from __future__ import annotations

from enum import StrEnum

from lsp_overlay.domain.pose import Pose

ANGLE_FIELDS: frozenset[str] = frozenset({"rx", "ry", "rz"})


class FieldKey(StrEnum):
    """Имена полей так, как они называются в панели игры (в нижнем регистре)."""

    X = "x"
    Y = "y"
    Z = "z"
    RX = "rx"
    RY = "ry"
    RZ = "rz"


FIELD_ORDER: tuple[FieldKey, ...] = (
    FieldKey.X,
    FieldKey.Y,
    FieldKey.Z,
    FieldKey.RX,
    FieldKey.RY,
    FieldKey.RZ,
)

TRANSLATION_FIELDS: tuple[FieldKey, ...] = (FieldKey.X, FieldKey.Y, FieldKey.Z)


def is_angle_field(key: FieldKey) -> bool:
    """Является ли поле углом (другая точность и допуск сравнения)."""
    return key.value in ANGLE_FIELDS


def get_field(pose: Pose, key: FieldKey) -> float:
    """Значение поля из позы."""
    return {
        FieldKey.X: pose.x,
        FieldKey.Y: pose.y,
        FieldKey.Z: pose.z,
        FieldKey.RX: pose.rx,
        FieldKey.RY: pose.ry,
        FieldKey.RZ: pose.rz,
    }[key]
