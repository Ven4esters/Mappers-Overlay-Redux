"""Запись изменившихся полей с проверкой результата."""

from __future__ import annotations

import logging
from typing import Final

from map_overlay.application.ports import PanelAutomation
from map_overlay.domain.fields import Field
from map_overlay.domain.formatting import check_decimals, format_value
from map_overlay.domain.movement import TOLERANCE, changed_fields
from map_overlay.domain.parsing import parse_number
from map_overlay.domain.pose import Pose
from map_overlay.errors import PanelRejectedError, ParseError

logger = logging.getLogger(__name__)

MAX_WRITE_ATTEMPTS: Final = 2
# Сколько раз пробуем записать поле: вставка идемпотентна, одной повторной попытки хватает.


class PoseWriter:
    """Пишет в панель только то, что действительно изменилось.

    После каждой вставки поле перечитывается: если панель не приняла значение, делается
    одна повторная попытка, затем поднимается :class:`PanelRejectedError` с ожидаемым и
    фактическим значением. Проверку можно отключить настройкой.
    """

    def __init__(self, panel: PanelAutomation, *, decimals: int, verify: bool) -> None:
        self._panel = panel
        self._decimals = check_decimals(decimals)
        self._verify = verify

    def write_changes(self, current: Pose, target: Pose) -> tuple[Field, ...]:
        """Записать отличающиеся поля; вернуть их список."""
        fields = changed_fields(current, target)
        for field in fields:
            self._write_field(field, target.value(field))
        return fields

    def _write_field(self, field: Field, value: float) -> None:
        text = format_value(value, self._decimals)
        seen = ""
        for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
            self._panel.write_field(field, text)
            if not self._verify:
                return
            try:
                seen = self._panel.read_field(field)
                actual = parse_number(seen)
            except ParseError as exc:
                logger.warning("Поле %s: не удалось перечитать (%s)", field.label, exc)
                continue
            if abs(actual - value) <= TOLERANCE:
                return
            logger.warning(
                "Поле %s не приняло %s (в поле %s), попытка %d из %d",
                field.label,
                text,
                seen,
                attempt,
                MAX_WRITE_ATTEMPTS,
            )
        raise PanelRejectedError(
            f"Панель не приняла поле {field.label}: ожидалось {text}, "
            f"в поле {seen.strip() or '—'}"
        )
