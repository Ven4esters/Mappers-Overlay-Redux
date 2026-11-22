"""Сессия маппинга: одна поза, список изменений и применение в игру."""

from __future__ import annotations

import logging
import threading

from lsp_overlay.application.diagnostics import DiagnosticReport, run_diagnostics
from lsp_overlay.application.errors import PanelUnavailableError
from lsp_overlay.application.ports import GamePanelPort
from lsp_overlay.application.writer import ApplyResult, FieldWriter
from lsp_overlay.config import Calibration, PanelTimings, Settings
from lsp_overlay.domain.catalog import Catalog, Dimension, ObjectSpec
from lsp_overlay.domain.directions import Direction
from lsp_overlay.domain.fields import FIELD_ORDER, FieldKey, get_field
from lsp_overlay.domain.join import JoinRequest, join_pose
from lsp_overlay.domain.measure import MeasureSlot, MeasureTape, Span
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

    def __init__(
        self,
        panel: GamePanelPort,
        settings: Settings,
        catalog: Catalog | None = None,
    ) -> None:
        self._panel = panel
        self._settings = settings
        self._writer = FieldWriter(panel, verify=settings.verify_after_paste)
        self._pose = Pose()
        self._panel_pose: Pose | None = None
        self._tape = MeasureTape()
        self._catalog = catalog or Catalog()
        self._pending_dimensions: dict[Dimension, float] = {}
        self._lock = threading.RLock()

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

    @property
    def catalog(self) -> Catalog:
        """Каталог предметов с габаритами."""
        return self._catalog

    def set_catalog(self, catalog: Catalog) -> None:
        """Заменяет каталог (загрузка из файла)."""
        self._catalog = catalog

    def save_object(self, spec: ObjectSpec) -> Catalog:
        """Добавляет или обновляет предмет в каталоге."""
        self._catalog = self._catalog.upsert(spec)
        LOGGER.info("Предмет сохранён в каталог: %s", spec.name)
        return self._catalog

    def remove_object(self, name: str) -> Catalog:
        """Удаляет предмет по названию."""
        self._catalog = self._catalog.remove(name)
        LOGGER.info("Предмет удалён из каталога: %s", name)
        return self._catalog

    @property
    def pending_dimensions(self) -> dict[Dimension, float]:
        """Измеренные габариты, ещё не сохранённые в каталог."""
        return dict(self._pending_dimensions)

    def record_dimension(self, dimension: Dimension) -> float | None:
        """Запоминает текущий замер как габарит предмета."""
        value = self.measurement(dimension)
        if value is not None:
            self._pending_dimensions[dimension] = value
        return value

    def clear_pending_dimensions(self) -> None:
        """Забывает измеренные габариты после сохранения предмета."""
        self._pending_dimensions.clear()

    def measurement(self, dimension: Dimension) -> float | None:
        """Значение измеренного габарита по последним двум точкам."""
        span = self._tape.span()
        if span is None or span.is_degenerate:
            return None
        return round(span.dimension_value(dimension), 3)

    def measurement_issue(self, dimension: Dimension) -> str | None:
        """Почему замер не стоит записывать в этот габарит (например, ось не та)."""
        span = self._tape.span()
        if span is None or span.is_degenerate:
            return None
        return span.axis_hint(dimension)

    def projections(self) -> dict[Dimension, float] | None:
        """Что выйдет по каждому габариту, если записать замер как есть."""
        span = self._tape.span()
        if span is None or span.is_degenerate:
            return None
        return span.projections()

    @property
    def span(self) -> Span | None:
        """Замер рулетки, если запомнены обе точки."""
        return self._tape.span()

    def tape_points(self) -> dict[MeasureSlot, Pose]:
        """Позы, сохранённые в рулетке."""
        return self._tape.points

    def remember_point(self, slot: MeasureSlot) -> Span | None:
        """Запоминает текущее положение пропа как точку замера."""
        self._tape.remember(slot, self._pose)
        LOGGER.info("Замер %s: %s", slot.label, self._pose.position)
        return self._tape.span()

    def clear_tape(self) -> None:
        """Забывает оба замера."""
        self._tape.clear()

    def diagnose(self) -> DiagnosticReport:
        """Проверяет, доходят ли клики и вставка до панели игры."""
        return run_diagnostics(self._panel)

    def capture(self) -> Pose:
        """Читает реальные координаты пропа и делает их точкой отсчёта."""
        with self._lock:
            return self._capture()

    def _capture(self) -> Pose:
        pose = self._panel.read_pose().rounded(self._settings.length_decimals, angle_decimals=2)
        self._pose = pose
        self._panel_pose = pose
        LOGGER.info("Считано из игры: %s", pose)
        return pose

    def move(self, direction: Direction, step: float | None = None) -> Pose:
        """Сдвигает проп в локальном направлении с учётом его углов."""
        with self._lock:
            return self._move(direction, step)

    def _move(self, direction: Direction, step: float | None) -> Pose:
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
        """Поля, которые отличаются от прочитанных из игры (их и пишем)."""
        if self._panel_pose is None:
            return FIELD_ORDER
        return tuple(
            key
            for key in FIELD_ORDER
            if abs(get_field(self._pose, key) - get_field(self._panel_pose, key)) > COMPARE_EPSILON
        )

    def join_target(
        self,
        first: ObjectSpec,
        second: ObjectSpec,
        request: JoinRequest,
        *,
        base: Pose | None = None,
    ) -> Pose:
        """Поза, в которую встанет второй предмет при стыке с первым."""
        return join_pose(base or self._pose, first, second, request).rounded(
            self._settings.length_decimals, angle_decimals=2
        )

    def place_join(
        self,
        first: ObjectSpec,
        second: ObjectSpec,
        request: JoinRequest,
        *,
        commit: bool = False,
    ) -> ApplyResult:
        """Ставит второй предмет вплотную к первому: считает позу и пишет её в панель."""
        with self._lock:
            target = self.join_target(first, second, request)
            ensure_within_limit(self._pose, target, self._settings.max_jump)
            self._pose = target
            LOGGER.info(
                "Стык %s %s° с «%s»: «%s» → %s",
                request.scheme.value,
                request.angle,
                first.name,
                second.name,
                target,
            )
            return self._apply(commit=commit)

    def apply(self, *, commit: bool = True) -> ApplyResult:
        """Пишет изменения в панель и (опционально) подтверждает ввод."""
        with self._lock:
            return self._apply(commit=commit)

    def clone_object(self) -> None:
        """Просит игру создать копию объекта (живой режим двигает копию)."""
        LOGGER.info("Клонирую объект клавишей %s", self._settings.clone_key)
        self._panel.tap_key(self._settings.clone_key)

    def delete_clone(self) -> None:
        """Нажимает клавишу удаления копии — только по явной команде пользователя."""
        LOGGER.info("Удаляю копию клавишей %s", self._settings.clone_delete_key)
        self._panel.tap_key(self._settings.clone_delete_key)

    def _apply(self, *, commit: bool) -> ApplyResult:
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
