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
    tilted: bool = False
    """Шаг считался по наклону ``RX`` (в интерфейсе — Alt)."""

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
        """Изменение Z (ненулевое только при шаге по наклону)."""
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
        self._panel.confirm()
        logger.info("Положение подтверждено клавишей F")

    def step(self, direction: Direction, step: float, *, tilt: bool = False) -> StepResult:
        """Сдвинуть предмет на шаг в направлении и записать изменения.

        ``tilt`` включает учёт наклона ``RX``: шаг идёт по наклонной плоскости.

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
        target = shifted(self._pose, direction, validate_step(step), tilt=tilt)
        written = self._writer.write_changes(self._pose, target)
        result = StepResult(previous=self._pose, pose=target, written=written, tilted=tilt)
        self._pose = target
        suffix = f" по наклону RX {self._pose.rx:.3f}°" if tilt else ""
        logger.info(
            "Шаг %s на %.3f м%s: записаны %s",
            direction.label,
            step,
            suffix,
            ", ".join(field.label for field in written) or "ничего",
        )
        return result
