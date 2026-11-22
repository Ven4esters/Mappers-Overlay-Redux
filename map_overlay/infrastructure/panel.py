"""Автоматизация панели LSP: клик по полю, ``Ctrl+A`` и копирование/вставка."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final

from map_overlay.application.ports import ClipboardPort, Clock, InputPort
from map_overlay.config import Delays
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.point import Point
from map_overlay.errors import CursorMovedError, NotCalibratedError

logger = logging.getLogger(__name__)

MAX_CURSOR_DRIFT_PX: Final = 4
"""Столько пикселей курсор может «дрожать» между нашими действиями."""


class CalibratedPanel:
    """Реализация :class:`map_overlay.application.ports.PanelAutomation`.

    Работает по точкам калибровки: клик в точку поля, затем клавиши. Перед каждым кликом
    сверяет позицию курсора с той, где мы его оставили: если пользователь двинул мышь,
    обмен прерывается, чтобы клик не попал в другое место панели.
    """

    def __init__(
        self,
        *,
        input_port: InputPort,
        clipboard: ClipboardPort,
        clock: Clock,
        points: Mapping[Field, Point],
        delays: Delays,
    ) -> None:
        self._input = input_port
        self._clipboard = clipboard
        self._clock = clock
        self._points = dict(points)
        self._delays = delays
        self._expected_cursor: Point | None = None

    def missing_points(self) -> tuple[Field, ...]:
        """Поля без точки калибровки."""
        return tuple(field for field in PANEL_ORDER if field not in self._points)

    def read_field(self, field: Field) -> str:
        """Прочитать поле: клик → ``Ctrl+A`` → ``Ctrl+C`` → буфер."""
        self._click(field)
        self._clock.sleep(self._delays.click)
        self._input.select_all()
        self._clock.sleep(self._delays.select)
        self._input.copy()
        self._clock.sleep(self._delays.copy)
        return self._clipboard.get()

    def write_field(self, field: Field, text: str) -> None:
        """Записать поле: буфер → клик → ``Ctrl+A`` → ``Ctrl+V``."""
        self._clipboard.set(text)
        self._click(field)
        self._clock.sleep(self._delays.click)
        self._input.select_all()
        self._clock.sleep(self._delays.select)
        self._input.paste()
        self._clock.sleep(self._delays.paste)

    def _click(self, field: Field) -> None:
        point = self._points.get(field)
        if point is None:
            raise NotCalibratedError(f"Поле {field.label} не откалибровано")
        self._check_cursor_still()
        self._input.click(point)
        self._expected_cursor = point

    def _check_cursor_still(self) -> None:
        if self._expected_cursor is None:
            return
        actual = self._input.cursor_position()
        drift_x = abs(actual.x - self._expected_cursor.x)
        drift_y = abs(actual.y - self._expected_cursor.y)
        if drift_x > MAX_CURSOR_DRIFT_PX or drift_y > MAX_CURSOR_DRIFT_PX:
            logger.warning("Курсор уехал с %s на %s — обмен прерван", self._expected_cursor, actual)
            raise CursorMovedError(
                "Курсор сдвинулся во время обмена с панелью — действие прервано, "
                "чтобы не кликнуть не туда. Повторите, не двигая мышь."
            )
