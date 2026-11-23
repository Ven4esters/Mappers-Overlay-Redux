"""Сессия работы с предметом: считать позу, сделать шаг."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from map_overlay.application.ports import PanelAutomation
from map_overlay.application.writer import PoseWriter
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.movement import shifted, validate_step
from map_overlay.domain.parsing import parse_number
from map_overlay.domain.pose import Pose
from map_overlay.errors import (
    AppError,
    ApplicationError,
    ClipboardError,
    InputError,
    NotCalibratedError,
    OperationCancelledError,
    PanelChangedError,
    PanelRejectedError,
    ParseError,
    PoseNotCapturedError,
)

logger = logging.getLogger(__name__)

PANEL_TROUBLE: tuple[type[Exception], ...] = (
    ClipboardError,
    InputError,
    OperationCancelledError,
    PanelChangedError,
    PanelRejectedError,
)
# Ошибки, после которых нельзя двигаться от прежних координат: состояние панели
# неизвестно, нужен новый «Считать».


@dataclass(frozen=True, slots=True)
class StepResult:
    """Итог одного шага: было, стало и какие поля переписаны."""

    previous: Pose
    pose: Pose
    written: tuple[Field, ...]
    tilted: bool = False
    """Шаг считался в режиме высоты (в интерфейсе — Alt): менялся ``Z``."""

    @property
    def delta_x(self) -> float:
        """Изменение X."""
        return self.pose.x - self.previous.x

    @property
    def delta_y(self) -> float:
        """Изменение Y."""
        return self.pose.y - self.previous.y

    @property
    def delta_z(self) -> float:
        """Изменение Z (ненулевое при шаге вверх/вниз и по диагонали на наклонённом предмете)."""
        return self.pose.z - self.previous.z


class MappingSession:
    """Сценарий: прочитать панель один раз, дальше двигать от считанных значений."""

    def __init__(self, panel: PanelAutomation, writer: PoseWriter) -> None:
        self._panel = panel
        self._writer = writer
        self._pose: Pose | None = None

    @property
    def pose(self) -> Pose | None:
        """Последняя считанная или записанная поза."""
        return self._pose

    def cancel(self) -> None:
        """Попросить прервать текущий обмен (кнопка «Прервать» или таймаут)."""
        self._panel.cancel()

    def ensure_calibrated(self) -> None:
        """Проверить, что у всех полей есть точка.

        Raises:
            NotCalibratedError: если калибровка неполная.
        """
        missing = self._panel.missing_points()
        if missing:
            titles = ", ".join(field.label for field in missing)
            raise NotCalibratedError(
                f"Не откалиброваны поля: {titles}. Откройте вкладку «Калибровка»."
            )

    def capture(self) -> Pose:
        """Прочитать все поля панели.

        Raises:
            NotCalibratedError: если калибровка неполная.
            ApplicationError: если поле вернуло не число.
        """
        self.ensure_calibrated()
        self._panel.reset_cancel()
        try:
            pose = self._read_pose()
        except AppError:
            # Недочитанная панель: прежние координаты больше не годятся.
            self._invalidate()
            raise
        self._pose = pose
        logger.info("Считано из панели: %s", pose)
        return pose

    def _read_pose(self) -> Pose:
        """Прочитать все поля по порядку панели.

        Raises:
            ApplicationError: если поле вернуло не число.
            OperationCancelledError: если действие прервали.
        """
        values: dict[Field, float] = {}
        for field in PANEL_ORDER:
            if self._panel.cancelled():
                raise OperationCancelledError("Действие отменено")
            raw = self._panel.read_field(field)
            try:
                values[field] = parse_number(raw)
            except ParseError as exc:
                raise ApplicationError(f"Поле {field.label}: {exc}") from exc
        return Pose(
            x=values[Field.X],
            y=values[Field.Y],
            z=values[Field.Z],
            rx=values[Field.RX],
            ry=values[Field.RY],
            rz=values[Field.RZ],
        )

    def confirm(self) -> None:
        """Зафиксировать текущее положение в игре: клик в пустое место и ``F``.

        Raises:
            NotCalibratedError: если точка «пустое место панели» не задана.
        """
        if not self._panel.has_confirmation_point():
            raise NotCalibratedError(
                "Не задана точка «пустое место панели»: без неё некуда кликнуть перед F. "
                "Откройте вкладку «Калибровка»."
            )
        self._panel.reset_cancel()
        try:
            self._panel.confirm()
        except PANEL_TROUBLE:
            self._invalidate()
            raise
        logger.info("Положение подтверждено клавишей F")

    def step(self, direction: Direction, step: float, *, tilt: bool = False) -> StepResult:
        """Сдвинуть предмет на шаг в направлении и записать изменения.

        ``tilt`` включает режим высоты: ``Num 8`` поднимает, ``Num 2`` опускает.

        Raises:
            PoseNotCapturedError: если поза ещё не считана.
            NotCalibratedError: если калибровка неполная.
            ValidationError: если шаг недопустим.
        """
        self.ensure_calibrated()
        if self._pose is None:
            raise PoseNotCapturedError(
                "Сначала нажмите «Считать»: оверлей не знает текущих координат"
            )
        self._panel.reset_cancel()
        target = shifted(self._pose, direction, validate_step(step), tilt=tilt)
        try:
            written = self._writer.write_changes(self._pose, target)
        except PANEL_TROUBLE as exc:
            logger.warning("Шаг отменён, координаты забыты: %s", exc)
            self._invalidate()
            raise
        result = StepResult(previous=self._pose, pose=target, written=written, tilted=tilt)
        self._pose = target
        if tilt and direction in (Direction.FORWARD, Direction.BACK):
            suffix = " (вверх)" if direction is Direction.FORWARD else " (вниз)"
        else:
            suffix = ""
        logger.info(
            "Шаг %s на %.3f м%s: записаны %s",
            direction.label,
            step,
            suffix,
            ", ".join(field.label for field in written) or "ничего",
        )
        return result

    def _invalidate(self) -> None:
        """Забыть позу: после сбоя панели двигаться от неё нельзя."""
        self._pose = None
