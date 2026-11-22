"""Автоматизация панели LSP: клик по полю, ``Ctrl+A`` и копирование/вставка."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final

from map_overlay.application.ports import ClipboardPort, Clock, InputPort
from map_overlay.config import Delays
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.point import Point
from map_overlay.errors import NotCalibratedError

logger = logging.getLogger(__name__)

MAX_CURSOR_DRIFT_PX: Final = 4
"""Столько пикселей курсор может «дрожать» между нашими действиями."""


class CalibratedPanel:
    """Реализация :class:`map_overlay.application.ports.PanelAutomation`.

    Работает по точкам калибровки: клик в точку поля, затем клавиши. Если пользователь
    двинул мышь, курсор возвращается в точку поля и обмен продолжается: клик всё равно
    наводится на откалиброванную точку, поэтому промахнуться невозможно.
    """

    def __init__(
        self,
        *,
        input_port: InputPort,
        clipboard: ClipboardPort,
        clock: Clock,
        points: Mapping[Field, Point],
        delays: Delays,
        empty_point: Point | None = None,
    ) -> None:
        self._input = input_port
        self._clipboard = clipboard
        self._clock = clock
        self._points = dict(points)
        self._delays = delays
        self._empty_point = empty_point
        self._expected_cursor: Point | None = None

    def missing_points(self) -> tuple[Field, ...]:
        """Поля без точки калибровки."""
        return tuple(field for field in PANEL_ORDER if field not in self._points)

    def has_confirmation_point(self) -> bool:
        """Задана ли точка «пустое место панели»."""
        return self._empty_point is not None

    def confirm(self) -> None:
        """Кликнуть в пустое место панели и нажать ``F``."""
        if self._empty_point is None:
            raise NotCalibratedError(
                "Точка «пустое место панели» не задана — клик перед F невозможен"
            )
        self._click_point(self._empty_point)
        self._clock.sleep(self._delays.click)
        self._input.press_f()
        logger.info("Нажато F в точке %s", self._empty_point)

    def read_field(self, field: Field) -> str:
        """Прочитать поле: клик → ``Ctrl+A`` → ``Ctrl+C`` → буфер."""
        logger.debug("Читаю поле %s", field.label)
        self._click(field)
        self._clock.sleep(self._delays.click)
        self._input.select_all()
        self._clock.sleep(self._delays.select)
        self._input.copy()
        self._clock.sleep(self._delays.copy)
        return self._clipboard.get()

    def write_field(self, field: Field, text: str) -> None:
        """Записать поле: буфер → клик → ``Ctrl+A`` → ``Ctrl+V``."""
        logger.debug("Пишу поле %s = %s", field.label, text)
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
        self._click_point(point)

    def _click_point(self, point: Point) -> None:
        self._return_cursor(point)
        self._input.click(point)
        self._expected_cursor = point

    def _return_cursor(self, point: Point) -> None:
        """Вернуть курсор в точку поля, если пользователь успел двинуть мышь."""
        if self._expected_cursor is None:
            return
        actual = self._input.cursor_position()
        drift_x = abs(actual.x - self._expected_cursor.x)
        drift_y = abs(actual.y - self._expected_cursor.y)
        if drift_x <= MAX_CURSOR_DRIFT_PX and drift_y <= MAX_CURSOR_DRIFT_PX:
            return
        logger.info(
            "Курсор уехал с %s на %s — возвращаю в %s", self._expected_cursor, actual, point
        )
        self._input.move_cursor(point)
