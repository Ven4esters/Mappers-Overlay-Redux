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
    ApplicationError,
    NotCalibratedError,
    ParseError,
    PoseNotCapturedError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StepResult:
    """Итог одного шага: было, стало и какие поля переписаны."""

    previous: Pose
    pose: Pose
    written: tuple[Field, ...]

    @property
    def delta_x(self) -> float:
        """Изменение X."""
        return self.pose.x - self.previous.x

    @property
    def delta_y(self) -> float:
        """Изменение Y."""
        return self.pose.y - self.previous.y


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
        values: dict[Field, float] = {}
        for field in PANEL_ORDER:
            raw = self._panel.read_field(field)
            try:
                values[field] = parse_number(raw)
            except ParseError as exc:
                raise ApplicationError(f"Поле {field.label}: {exc}") from exc
        pose = Pose(
            x=values[Field.X],
            y=values[Field.Y],
            z=values[Field.Z],
            rx=values[Field.RX],
            ry=values[Field.RY],
            rz=values[Field.RZ],
        )
        self._pose = pose
        logger.info("Считано из панели: %s", pose)
        return pose

    def step(self, direction: Direction, step: float) -> StepResult:
        """Сдвинуть предмет на шаг в направлении и записать изменения.

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
        target = shifted(self._pose, direction, validate_step(step))
        written = self._writer.write_changes(self._pose, target)
        result = StepResult(previous=self._pose, pose=target, written=written)
        self._pose = target
        logger.info(
            "Шаг %s на %.3f м: записаны %s",
            direction.label,
            step,
            ", ".join(field.label for field in written) or "ничего",
        )
        return result
