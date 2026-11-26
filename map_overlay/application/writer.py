"""Запись изменившихся полей с проверкой результата."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Final

from map_overlay.application.ports import PanelAutomation
from map_overlay.domain.fields import Field
from map_overlay.domain.formatting import check_decimals, format_value
from map_overlay.domain.movement import TOLERANCE, changed_fields
from map_overlay.domain.parsing import parse_number
from map_overlay.domain.pose import Pose
from map_overlay.errors import (
    OperationCancelledError,
    PanelChangedError,
    PanelRejectedError,
    ParseError,
)
from map_overlay.trace import note, timed

logger = logging.getLogger(__name__)

MAX_WRITE_ATTEMPTS: Final = 2
# Сколько раз пробуем записать поле: вставка идемпотентна, одной повторной попытки хватает.

SELF_WRITE_GRACE_S: Final = 2.0
# Сколько секунд после своей записи не перечитывать поле X: оверлей только что сам
# поставил там значение, и лишнее чтение (0.16 с) тормозит каждый шаг (ADR-0051).

MAX_SELF_WRITE_GRACE_S: Final = 10.0
# Верхняя граница паузы доверия: дольше держать «токен» нельзя — за это время предмет
# могли подвинуть в игре, и сверка обязана сработать.

PANEL_DRIFT_M: Final = 0.01
# Допустимое расхождение между значением в панели и тем, что помнит оверлей.
# Сантиметр: панель может показывать два знака (округление до 5 мм), а «вписали другое
# значение» — это всегда заметно больше сантиметра.


class PoseWriter:
    """Пишет в панель только то, что действительно изменилось.

    После каждой вставки поле перечитывается: если панель не приняла значение, делается
    одна повторная попытка, затем поднимается :class:`PanelRejectedError` с ожидаемым и
    фактическим значением. Проверку можно отключить настройкой.

    Перед первой записью сверяется поле ``X``: если в панели уже другое значение (его
    вписали руками, панель переоткрылась, выбран другой предмет), запись не начинается —
    поднимается :class:`PanelChangedError`. Иначе оверлей затирал бы чужое значение и
    дальше считал от неверных координат.

    Сразу после своей же записи сверка пропускается: ``self_write_grace`` секунд оверлей
    помнит, что именно он поставил в панель, и не перечитывает ``X`` зря. Пауза кончилась
    или поза в памяти разошлась с токеном — сверка возвращается.
    """

    def __init__(
        self,
        panel: PanelAutomation,
        *,
        decimals: int,
        verify: bool,
        self_write_grace: float = SELF_WRITE_GRACE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 <= self_write_grace <= MAX_SELF_WRITE_GRACE_S:
            raise ValueError(
                f"Пауза доверия к своей записи должна быть от 0 до {MAX_SELF_WRITE_GRACE_S} с, "
                f"получено {self_write_grace}"
            )
        self._panel = panel
        self._decimals = check_decimals(decimals)
        self._verify = verify
        self._self_write_grace = self_write_grace
        self._clock = clock
        self._self_write: tuple[float, Pose] | None = None

    def write_changes(
        self, current: Pose, target: Pose, *, expect_panel: bool = True
    ) -> tuple[Field, ...]:
        """Записать отличающиеся поля; вернуть их список.

        ``expect_panel=False`` отключает сверку «панель та же»: так пишет вставка
        координат, которая перезаписывает текущий предмет намеренно. Проверка каждого
        записанного поля после вставки при этом остаётся.

        Raises:
            PanelChangedError: если в панели уже другое значение.
            PanelRejectedError: если панель не приняла записанное.
            OperationCancelledError: если действие прервали.
        """
        fields = changed_fields(current, target)
        if not fields:
            note("менять нечего: все поля совпали")
            return fields
        note(
            "пишу поля: %s",
            ", ".join(field.label for field in fields),
        )
        if expect_panel and not self._is_self_write(current):
            self._check_panel_matches(current)
        for field in fields:
            if self._panel.cancelled():
                raise OperationCancelledError("Действие отменено")
            self._write_field(field, target.value(field))
        self._self_write = (self._clock(), target)
        return fields

    def _is_self_write(self, current: Pose) -> bool:
        """Это поза, которую оверлей сам только что записал?

        Сверка ``X`` нужна, чтобы не затереть чужое значение, но сразу после своей записи
        она лишь повторяет прочитанное. Токен живёт ``self_write_grace`` секунд и только
        пока поза в памяти совпадает с записанной: разошлись — сверка выполняется как обычно.
        """
        if self._self_write_grace <= 0.0 or self._self_write is None:
            return False
        written_at, written_pose = self._self_write
        age = self._clock() - written_at
        if age > self._self_write_grace:
            return False
        if changed_fields(written_pose, current, tolerance=PANEL_DRIFT_M):
            return False
        note("своя запись %.1f с назад: сверку поля X пропускаю", age)
        return True

    def _check_panel_matches(self, current: Pose) -> None:
        """Убедиться, что панель всё ещё показывает ту позу, от которой считается шаг.

        Raises:
            PanelChangedError: если значение в поле ``X`` другое.
        """
        if not self._verify:
            return
        with timed("сверка панели: поле X"):
            raw = self._panel.read_field(Field.X)
        try:
            actual = parse_number(raw)
        except ParseError as exc:
            raise PanelChangedError(
                f"Поле X не читается ({exc}): панель закрыта или в ней другое значение. "
                "Нажмите «Считать» и повторите"
            ) from exc
        if abs(actual - current.x) <= PANEL_DRIFT_M:
            note("панель та же: X = %.3f", actual)
            return
        logger.warning(
            "Панель изменилась: X = %s, оверлей помнит %.3f — запись отменена",
            actual,
            current.x,
        )
        raise PanelChangedError(
            f"В панели X = {format_value(actual, self._decimals)}, а оверлей считал "
            f"{format_value(current.x, self._decimals)}: значение изменили. "
            "Нажмите «Считать» и повторите"
        )

    def _write_field(self, field: Field, value: float) -> None:
        text = format_value(value, self._decimals)
        seen = ""
        for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
            self._panel.write_field(field, text)
            if not self._verify:
                note("поле %s записано без проверки (%s)", field.label, text)
                return
            try:
                seen = self._panel.read_field(field)
                actual = parse_number(seen)
            except ParseError as exc:
                logger.warning("Поле %s: не удалось перечитать (%s)", field.label, exc)
                continue
            if abs(actual - value) <= TOLERANCE:
                note("поле %s принято: %s", field.label, text)
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
