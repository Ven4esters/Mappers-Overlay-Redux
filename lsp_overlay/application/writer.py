"""Запись значений в панель игры с проверкой «на месте ли проп»."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from lsp_overlay.application.errors import ApplyError, PanelUnavailableError
from lsp_overlay.application.ports import GamePanelPort
from lsp_overlay.domain.fields import FieldKey, get_field, is_angle_field
from lsp_overlay.domain.pose import Pose
from lsp_overlay.domain.safety import values_match

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Что именно записали и подтвердилось ли это чтением."""

    fields: tuple[FieldKey, ...]
    verified: bool
    pose: Pose


class FieldWriter:
    """Пишет только изменившиеся поля и перечитывает их после вставки.

    Если панель не приняла значение (промах клика, не сработал ``Ctrl+A``,
    дописанные цифры), прежние значения возвращаются в поля, а наружу летит
    :class:`ApplyError`. Это и есть защита от «улёта» пропа.
    """

    def __init__(self, panel: GamePanelPort, *, verify: bool = True) -> None:
        self._panel = panel
        self._verify = verify

    def write(self, previous: Pose, target: Pose, fields: Sequence[FieldKey]) -> ApplyResult:
        """Записывает поля из ``target``, при ошибке откатывает к ``previous``."""
        if not self._panel.is_available():
            raise PanelUnavailableError(
                "Панель игры недоступна: задайте точки в «Калибровке» и откройте меню пропа."
            )
        ordered = tuple(fields)
        if not ordered:
            return ApplyResult(fields=(), verified=False, pose=target)

        self._panel.write_fields({key: get_field(target, key) for key in ordered})
        if not self._verify:
            return ApplyResult(fields=ordered, verified=False, pose=target)

        try:
            mismatched = self._mismatched(target, ordered)
        except PanelUnavailableError as error:
            rolled_back = self._rollback(previous, ordered)
            raise ApplyError(
                f"Не удалось проверить записанные значения: {error}",
                rolled_back=rolled_back,
            ) from error
        if mismatched:
            rolled_back = self._rollback(previous, ordered)
            raise ApplyError(
                "Панель не приняла значения ("
                + ", ".join(key.value.upper() for key in mismatched)
                + "). "
                + ("Прежние координаты возвращены." if rolled_back else "Откат не удался."),
                rolled_back=rolled_back,
            )
        LOGGER.debug("Записано и проверено: %s", [key.value for key in ordered])
        return ApplyResult(fields=ordered, verified=True, pose=target)

    def _mismatched(self, target: Pose, fields: Sequence[FieldKey]) -> list[FieldKey]:
        actual = self._panel.read_pose()
        return [
            key
            for key in fields
            if not values_match(
                get_field(target, key),
                get_field(actual, key),
                angle=is_angle_field(key),
            )
        ]

    def _rollback(self, previous: Pose, fields: Sequence[FieldKey]) -> bool:
        try:
            self._panel.write_fields({key: get_field(previous, key) for key in fields})
        except Exception:  # noqa: BLE001 - откат best-effort, причина уже залогирована ниже
            LOGGER.exception("Не удалось вернуть прежние значения полей")
            return False
        return True
