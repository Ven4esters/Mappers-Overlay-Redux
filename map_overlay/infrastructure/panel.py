"""Автоматизация панели LSP: клик по полю, ``Ctrl+A`` и копирование/вставка."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final

from map_overlay.application.ports import ClipboardPort, Clock, InputPort
from map_overlay.config import Delays
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.point import Point
from map_overlay.errors import ClipboardError, NotCalibratedError

logger = logging.getLogger(__name__)

MAX_CURSOR_DRIFT_PX: Final = 4

MODIFIER_WAIT_S: Final = 1.5
"""Сколько ждать отпускания ``Alt``/``Ctrl``/``Shift`` перед обменом."""

MODIFIER_POLL_S: Final = 0.05
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
        self._wait_modifiers_released()
        self._click_point(self._empty_point)
        self._clock.sleep(self._delays.click)
        self._input.press_f()
        logger.info("Нажато F в точке %s", self._empty_point)

    def read_field(self, field: Field) -> str:
        """Прочитать поле: клик → ``Ctrl+A`` → ``Ctrl+C`` → буфер.

        Перед копированием буфер очищается. Без этого несостоявшееся копирование
        возвращало бы то, что оверлей сам же в буфер и положил (например при записи),
        и проверка «значение принято?» подтверждала бы несуществующий успех.

        Raises:
            ClipboardError: если панель не отдала значение — буфер остался пустым.
        """
        logger.debug("Читаю поле %s", field.label)
        self._wait_modifiers_released()
        self._clipboard.set("")
        self._click(field)
        self._clock.sleep(self._delays.click)
        self._input.select_all()
        self._clock.sleep(self._delays.select)
        self._input.copy()
        self._clock.sleep(self._delays.copy)
        text = self._clipboard.get()
        if not text.strip():
            raise ClipboardError(
                f"Поле {field.label} не отдало значение: панель не получила Ctrl+C. "
                "Проверьте, что окно панели на экране и не перекрыто"
            )
        return text

    def write_field(self, field: Field, text: str) -> None:
        """Записать поле: буфер → клик → ``Ctrl+A`` → ``Ctrl+V``."""
        logger.debug("Пишу поле %s = %s", field.label, text)
        self._wait_modifiers_released()
        self._clipboard.set(text)
        self._click(field)
        self._clock.sleep(self._delays.click)
        self._input.select_all()
        self._clock.sleep(self._delays.select)
        self._input.paste()
        self._clock.sleep(self._delays.paste)

    def _wait_modifiers_released(self) -> None:
        """Дождаться, пока пользователь отпустит ``Alt``/``Ctrl``/``Shift``.

        Иначе ``Ctrl+A`` уходит в игру как ``Alt+Ctrl+A``: в поле появляется лишний
        символ, значение не читается, и обмен повторяется впустую — со стороны это
        выглядит как зависание.
        """
        waited = 0.0
        while waited < MODIFIER_WAIT_S and self._input.modifier_down():
            self._clock.sleep(MODIFIER_POLL_S)
            waited += MODIFIER_POLL_S
        if waited:
            logger.info("Ждал отпускания модификаторов %.2f с", waited)

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
