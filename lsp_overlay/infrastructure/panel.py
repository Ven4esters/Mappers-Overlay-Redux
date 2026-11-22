"""Панель LSP как «железо»: клики, Ctrl+A/C/V и подтверждение клавишей F."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence

from lsp_overlay.application.errors import PanelUnavailableError
from lsp_overlay.config import Calibration, PanelTimings, Point
from lsp_overlay.domain.errors import DomainError
from lsp_overlay.domain.fields import FieldKey, is_angle_field
from lsp_overlay.domain.formatting import format_angle, format_length, parse_number
from lsp_overlay.domain.pose import Pose
from lsp_overlay.infrastructure.clipboard import ClipboardError, ClipboardPort
from lsp_overlay.infrastructure.win32_input import InputBackend, InputUnavailableError

LOGGER = logging.getLogger(__name__)
DEFAULT_SLEEP: Callable[[float], None] = time.sleep
READ_ATTEMPTS = 2
CLIPBOARD_POLL = 0.004
CURSOR_TOLERANCE = 4
MARKER_PREFIX = "lsp-overlay-marker"


class ClipboardPanel:
    """Читает и пишет шесть полей левой панели через буфер обмена.

    Подтверждение ввода на этой сборке LSP — левый клик в пустое место панели и
    клавиша ``F`` (ADR-0003), поэтому :meth:`commit` не нажимает ``Enter``.
    """

    def __init__(
        self,
        input_backend: InputBackend,
        clipboard: ClipboardPort,
        *,
        calibration: Calibration,
        timings: PanelTimings | None = None,
        length_decimals: int = 4,
        confirm_key: str = "f",
        sleep: Callable[[float], None] = DEFAULT_SLEEP,
    ) -> None:
        self._input = input_backend
        self._clipboard = clipboard
        self._calibration = calibration
        self._timings = timings or PanelTimings()
        self._length_decimals = length_decimals
        self._confirm_key = confirm_key
        self._sleep = sleep
        self._marker_seq = 0

    def is_available(self) -> bool:
        """Готова ли панель: есть калибровка и доступен ввод."""
        return self._calibration.is_complete and self._input.is_ready()

    def configure(
        self,
        *,
        calibration: Calibration,
        timings: PanelTimings,
        length_decimals: int,
        confirm_key: str,
    ) -> None:
        """Применяет изменённые настройки без пересоздания панели."""
        self._calibration = calibration
        self._timings = timings
        self._length_decimals = length_decimals
        self._confirm_key = confirm_key

    def read_pose(self) -> Pose:
        """Читает все шесть полей."""
        values = self.read_fields(tuple(FieldKey))
        return Pose(**{key.value: values[key] for key in FieldKey})

    def read_fields(self, keys: Sequence[FieldKey]) -> dict[FieldKey, float]:
        """Читает только указанные поля — быстрее, чем вся панель."""
        return {key: self.read_field(key) for key in keys}

    def read_field(self, key: FieldKey) -> float:
        """Читает одно поле; если в буфере мусор — пробует ещё раз."""
        last_error: DomainError | None = None
        for _attempt in range(READ_ATTEMPTS):
            try:
                return self._read_field_once(key)
            except DomainError as error:
                last_error = error
                LOGGER.warning("Поле %s не прочиталось, повтор: %s", key.value.upper(), error)
        raise PanelUnavailableError(str(last_error)) from last_error

    def _read_field_once(self, key: FieldKey) -> float:
        point = self._point(key)
        self._focus(point)
        marker = self._write_marker()
        self._click(point)
        self._input.press_combination("ctrl", "a")
        self._sleep(self._timings.field)
        self._input.press_combination("ctrl", "c")
        text = self._wait_for_clipboard(marker)
        try:
            return parse_number(text)
        except DomainError as error:
            raise PanelUnavailableError(
                f"поле {key.value.upper()} прочитано как «{text}» — это не число. "
                "Закройте уведомления поверх игры, проверьте калибровку или нажмите F."
            ) from error

    def write_fields(self, values: Mapping[FieldKey, float]) -> None:
        """Пишет значения только в указанные поля."""
        points = {key: self._point(key) for key in values}
        if points:
            self._focus(next(iter(points.values())))
        for key, value in values.items():
            point = points[key]
            self._click(point)
            self._input.press_combination("ctrl", "a")
            self._sleep(self._timings.field)
            # в поле пишем чистое число: «°» оставляем только для отображения в оверлее
            text = (
                format_angle(value, with_sign=False)
                if is_angle_field(key)
                else format_length(value, self._length_decimals)
            )
            try:
                self._clipboard.set_text(text)
            except ClipboardError as error:
                raise PanelUnavailableError(str(error)) from error
            self._input.press_combination("ctrl", "v")
            self._sleep(self._timings.paste)
            LOGGER.debug("Поле %s = %s", key.value.upper(), text)

    def commit(self) -> None:
        """Кликает в пустое место панели и жмёт клавишу подтверждения."""
        placeholder = self._calibration.placeholder
        if placeholder is None:
            raise PanelUnavailableError("не задано «пустое место» — откройте «Калибровку»")
        self._focus(placeholder)
        self._input.click(*placeholder.as_tuple())
        self._sleep(self._timings.commit)
        try:
            self._input.tap_key(self._confirm_key)
        except InputUnavailableError as error:
            raise PanelUnavailableError(str(error)) from error
        self._sleep(self._timings.commit)

    def tap_key(self, key: str) -> None:
        """Нажимает клавишу в окне игры, предварительно убедившись, что оно активно."""
        placeholder = self._calibration.placeholder
        if placeholder is None:
            raise PanelUnavailableError("не задано «пустое место» — откройте «Калибровку»")
        self._focus(placeholder)
        try:
            self._input.tap_key(key)
        except InputUnavailableError as error:
            raise PanelUnavailableError(str(error)) from error
        self._sleep(self._timings.commit)

    def _click(self, point: Point) -> None:
        """Кликает и проверяет, что курсор остался на месте: мышь могла сдвинуть рукой.

        Пока идёт макрос, двигать мышью нельзя: промах клика пишет число в чужое поле.
        """
        self._input.click(*point.as_tuple())
        self._sleep(self._timings.click)
        position = self._input.cursor_position()
        if position is None:
            return
        if (
            abs(position[0] - point.x) > CURSOR_TOLERANCE
            or abs(position[1] - point.y) > CURSOR_TOLERANCE
        ):
            raise PanelUnavailableError(
                "курсор сдвинули во время макроса — не двигайте мышь, пока идёт ввод"
            )

    def _write_marker(self) -> str:
        """Кладёт в буфер уникальную метку: по ней видно, что ``Ctrl+C`` уже сработал."""
        marker = f"{MARKER_PREFIX}{self._marker_seq}"
        self._marker_seq += 1
        try:
            self._clipboard.set_text(marker)
        except ClipboardError:
            LOGGER.debug("Не удалось положить метку в буфер, читаю как есть")
        return marker

    def _wait_for_clipboard(self, marker: str) -> str:
        """Ждёт, пока в буфере появится текст поля, но не дольше таймаута."""
        deadline = self._timings.clipboard
        waited = 0.0
        text = marker
        while waited <= deadline:
            try:
                text = self._clipboard.get_text()
            except ClipboardError as error:
                raise PanelUnavailableError(str(error)) from error
            if text != marker and text.strip():
                return text
            self._sleep(CLIPBOARD_POLL)
            waited += CLIPBOARD_POLL
        return text

    def _focus(self, point: Point) -> None:
        """Активирует окно игры, если оно не в фокусе: первый клик иначе съедается."""
        try:
            activated = self._input.ensure_foreground(point.x, point.y)
        except InputUnavailableError as error:
            raise PanelUnavailableError(str(error)) from error
        if activated:
            LOGGER.debug("Окно игры было не в фокусе — активировал кликом")
            self._sleep(self._timings.focus)

    def _point(self, key: FieldKey) -> Point:
        point = self._calibration.fields.get(key)
        if point is None:
            raise PanelUnavailableError(
                f"нет точки для поля {key.value.upper()} — откройте «Калибровку»"
            )
        return point
