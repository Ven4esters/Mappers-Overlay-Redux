"""Сессия маппинга: одна поза, список изменений и применение в игру."""

from __future__ import annotations

import logging

from lsp_overlay.application.errors import PanelUnavailableError
from lsp_overlay.application.ports import GamePanelPort
from lsp_overlay.application.writer import ApplyResult, FieldWriter
from lsp_overlay.config import Calibration, PanelTimings, Settings
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.fields import FIELD_ORDER, FieldKey, get_field
from lsp_overlay.domain.movement import move, rotate
from lsp_overlay.domain.pose import Axis, Pose
from lsp_overlay.domain.safety import ensure_within_limit

LOGGER = logging.getLogger(__name__)
COMPARE_EPSILON = 1e-6


class MappingSession:
    """Хранит текущую позу пропа и знает, что нужно записать в игру.

    Единственный источник правды о «где проп сейчас» — результат чтения панели
    (:meth:`capture`). Все кнопки меняют только локальную позу; в игру значения
    попадают в :meth:`apply`.
    """

    def __init__(self, panel: GamePanelPort, settings: Settings) -> None:
        self._panel = panel
        self._settings = settings
        self._writer = FieldWriter(panel, verify=settings.verify_after_paste)
        self._pose = Pose()
        self._panel_pose: Pose | None = None

    @property
    def pose(self) -> Pose:
        """Желаемая поза (то, что будет записано)."""
        return self._pose

    @property
    def panel_pose(self) -> Pose | None:
        """Поза, прочитанная из игры в последний раз."""
        return self._panel_pose

    @property
    def settings(self) -> Settings:
        """Текущие настройки сессии."""
        return self._settings

    def update_settings(self, settings: Settings) -> None:
        """Применяет новые настройки (проверка записи пересоздаётся)."""
        self._settings = settings
        self._writer = FieldWriter(self._panel, verify=settings.verify_after_paste)

    def configure_panel(
        self,
        *,
        calibration: Calibration,
        timings: PanelTimings,
        length_decimals: int,
        confirm_key: str,
    ) -> None:
        """Передаёт панели точки калибровки и параметры ввода."""
        self._panel.configure(
            calibration=calibration,
            timings=timings,
            length_decimals=length_decimals,
            confirm_key=confirm_key,
        )

    def capture(self) -> Pose:
        """Читает реальные координаты пропа и делает их точкой отсчёта."""
        pose = self._panel.read_pose().rounded(self._settings.length_decimals, angle_decimals=2)
        self._pose = pose
        self._panel_pose = pose
        LOGGER.info("Считано из игры: %s", pose)
        return pose

    def move(self, direction: Direction, step: float | None = None) -> Pose:
        """Сдвигает проп в локальном направлении с учётом его углов."""
        distance = self._settings.step if step is None else step
        candidate = move(
            self._pose,
            direction,
            distance,
            diagonal_mode=self._settings.diagonal_mode,
            use_tilt=self._settings.use_tilt,
        ).rounded(self._settings.length_decimals)
        ensure_within_limit(self._pose, candidate, self._settings.max_jump)
        self._pose = candidate
        return candidate

    def rotate(self, axis: Axis, degrees: float) -> Pose:
        """Поворачивает проп вокруг оси; угол нормализуется к ``[-180, 180)``."""
        self._pose = rotate(self._pose, axis, degrees).rounded(self._settings.length_decimals)
        return self._pose

    def set_field(self, key: FieldKey, value: float) -> Pose:
        """Ручной ввод одного поля (например, «угол 37.5° вручную»)."""
        if key in (FieldKey.RX, FieldKey.RY, FieldKey.RZ):
            self._pose = self._pose.with_angle(Axis(key.value), value)
        else:
            delta = {
                FieldKey.X: (value - self._pose.x, 0.0, 0.0),
                FieldKey.Y: (0.0, value - self._pose.y, 0.0),
                FieldKey.Z: (0.0, 0.0, value - self._pose.z),
            }[key]
            self._pose = self._pose.translated(delta)
        self._pose = self._pose.rounded(self._settings.length_decimals)
        return self._pose

    def reset_to_panel(self) -> Pose | None:
        """Отбрасывает неприменённые изменения."""
        self._pose = self._panel_pose or self._pose
        return self._panel_pose

    def pending_fields(self) -> tuple[FieldKey, ...]:
        """Поля, которые отличаются от прочитанных из игры."""
        if self._panel_pose is None:
            return FIELD_ORDER
        return tuple(
            key
            for key in FIELD_ORDER
            if abs(get_field(self._pose, key) - get_field(self._panel_pose, key)) > COMPARE_EPSILON
        )

    def apply(self, *, commit: bool = True) -> ApplyResult:
        """Пишет изменения в панель и (опционально) подтверждает ввод."""
        if self._panel_pose is None:
            raise PanelUnavailableError(
                "Сначала нажмите «Считать из игры» — без этого неизвестно, где проп сейчас."
            )
        fields = self.pending_fields()
        result = self._writer.write(self._panel_pose, self._pose, fields)
        if commit and result.fields:
            self._panel.commit()
        self._panel_pose = self._pose
        return result

    def clone_object(self) -> None:
        """Просит игру создать копию объекта: живой режим двигает именно копию."""
        LOGGER.info("Клонирую объект клавишей %s", self._settings.clone_key)
        self._panel.tap_key(self._settings.clone_key)

    def delete_clone(self) -> None:
        """Нажимает клавишу удаления копии — только по явной команде пользователя."""
        LOGGER.info("Удаляю копию клавишей %s", self._settings.clone_delete_key)
        self._panel.tap_key(self._settings.clone_delete_key)
