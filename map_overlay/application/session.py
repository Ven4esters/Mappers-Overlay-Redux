"""Сессия работы с предметом: считать позу, сделать шаг."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from map_overlay.application.ports import PanelAutomation
from map_overlay.application.writer import PoseWriter
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import PANEL_ORDER, Field
from map_overlay.domain.movement import changed_fields, shifted, validate_step
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
from map_overlay.trace import note, timed

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

    reread: bool = False
    """Перед шагом поля читались заново (режим «Всегда считать позицию»)."""

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


@dataclass(frozen=True, slots=True)
class PasteResult:
    """Итог вставки координат: что было у получателя, что вписали и какие поля изменились."""

    previous: Pose
    """Поза получателя до вставки: по ней работает Ctrl+Z."""
    pose: Pose
    """Поза, которая ушла в панель (координаты и углы источника)."""
    written: tuple[Field, ...]

    @property
    def changed(self) -> bool:
        """Появились ли изменения: если получатель уже стоял там же, писать нечего."""
        return bool(self.written)


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
        with timed("считать координаты из панели"):
            self.ensure_calibrated()
            self._panel.reset_cancel()
            pose = self._read_with_recovery()
        self._pose = pose
        logger.info("Считано из панели: %s", pose)
        return pose

    def _read_with_recovery(self) -> Pose:
        """Прочитать панель; при сбое забыть старые координаты и пробросить ошибку.

        Raises:
            AppError: любая ошибка обмена с панелью.
        """
        try:
            return self._read_pose()
        except AppError:
            # Недочитанная панель: прежние координаты больше не годятся.
            self._invalidate()
            raise

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
            with timed("сохранить F"):
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
        label = f"шаг {direction.label} {step:g} м" + (" (высота)" if tilt else "")
        note(
            "%s: от %s к %s",
            label,
            _pose_text(self._pose),
            _pose_text(target),
        )
        try:
            with timed(label):
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

    def paste(self, source: Pose) -> PasteResult:
        """Вписать позу одного предмета в текущий предмет панели.

        Получатель — тот предмет, что открыт в панели сейчас. Сначала оверлей читает его
        позу (без этого нечего отменять и незачем сверять), потом переписывает отличающиеся
        поля на значения ``source``. Сверка «панель та же» здесь не нужна и вредна: старая
        поза принадлежит другому предмету, а перезапись — намеренная. Нажатие ``F`` вставка
        не делает: предмет встаёт на место, когда пользователь сам его подтвердит.

        ``source`` — координаты и углы, снятые кнопкой «Считать» (или шагами от них).

        Raises:
            NotCalibratedError: если калибровка неполная.
            ApplicationError: если поле получателя вернуло не число.
            PanelRejectedError: если панель не приняла записанное.
            OperationCancelledError: если действие прервали.
        """
        with timed("вставить координаты"):
            self.ensure_calibrated()
            self._panel.reset_cancel()
            try:
                before = self._read_pose()
                note(
                    "вставка координат: получатель %s, источник %s",
                    _pose_text(before),
                    _pose_text(source),
                )
                written = self._writer.write_changes(before, source, expect_panel=False)
            except AppError as exc:
                logger.warning("Вставка не удалась, координаты забыты: %s", exc)
                self._invalidate()
                raise
        self._pose = source
        logger.info(
            "Координаты вставлены: получатель был %s, стал %s; записаны %s",
            _pose_text(before),
            _pose_text(source),
            ", ".join(field.label for field in written) or "ничего",
        )
        return PasteResult(previous=before, pose=source, written=written)

    def capture_and_step(
        self, direction: Direction, step: float, *, tilt: bool = False
    ) -> StepResult:
        """Прочитать панель и сразу сдвинуть предмет от прочитанных координат.

        Так работает режим «Всегда считать позицию»: шаг считается не от запомненной позы,
        а от той, что стоит в полях прямо сейчас, поэтому «Считать» перед каждым шагом не
        нужно, а расхождение (предмет подвинули в игре или выбрали другой) не мешает: шаг
        всё равно выполняется, просто от свежих чисел.

        ``tilt`` включает режим высоты: ``Num 8`` поднимает, ``Num 2`` опускает.

        Raises:
            NotCalibratedError: если калибровка неполная.
            ApplicationError: если поле панели вернуло не число.
            ValidationError: если шаг недопустим.
            PanelRejectedError: если панель не приняла записанное.
            OperationCancelledError: если действие прервали.
        """
        self.ensure_calibrated()
        self._panel.reset_cancel()
        note("режим «всегда считать позицию»: читаю поля перед шагом")
        try:
            before = self._read_pose()
        except AppError as exc:
            logger.warning("Чтение перед шагом не удалось, координаты забыты: %s", exc)
            self._invalidate()
            raise
        changed = self._pose is None or bool(changed_fields(self._pose, before))
        if changed:
            logger.info("Позиция прочитана заново: %s", _pose_text(before))
        target = shifted(before, direction, validate_step(step), tilt=tilt)
        label = f"шаг {direction.label} {step:g} м" + (" (высота)" if tilt else "")
        note("%s от прочитанного: %s к %s", label, _pose_text(before), _pose_text(target))
        try:
            with timed(label):
                written = self._writer.write_changes(before, target, expect_panel=False)
        except PANEL_TROUBLE as exc:
            logger.warning("Шаг отменён, координаты забыты: %s", exc)
            self._invalidate()
            raise
        result = StepResult(previous=before, pose=target, written=written, tilted=tilt, reread=True)
        self._pose = target
        logger.info(
            "Шаг %s на %.3f м после чтения: записаны %s",
            direction.label,
            step,
            ", ".join(field.label for field in written) or "ничего",
        )
        return result

    def restore(self, pose: Pose, *, full: bool = False) -> StepResult:
        """Вернуть предмет к сохранённой позе — так работает отмена шага (Ctrl+Z).

        Меняются только координаты: углы остаются текущими, потому что шаг их не меняет,
        а отменяется именно сдвиг. Координаты берутся из сохранённой позы, а не считаются
        обратным шагом: так в панель уходят ровно те числа, что были до шага.

        ``full=True`` возвращает и углы: вставка координат переписывает позу целиком, значит
        и отменять её нужно целиком.

        Raises:
            PoseNotCapturedError: если поза ещё не считана.
            NotCalibratedError: если калибровка неполная.
        """
        self.ensure_calibrated()
        if self._pose is None:
            raise PoseNotCapturedError(
                "Сначала нажмите «Считать»: оверлей не знает текущих координат"
            )
        current = self._pose
        target = pose if full else replace(current, x=pose.x, y=pose.y, z=pose.z)
        self._panel.reset_cancel()
        note(
            "возврат координат: от %s к %s",
            _pose_text(current),
            _pose_text(target),
        )
        try:
            with timed("возврат координат"):
                written = self._writer.write_changes(current, target)
        except PANEL_TROUBLE as exc:
            logger.warning("Возврат координат не удался, координаты забыты: %s", exc)
            self._invalidate()
            raise
        result = StepResult(previous=current, pose=target, written=written, tilted=False)
        self._pose = target
        logger.info(
            "Координаты возвращены: записаны %s",
            ", ".join(field.label for field in written) or "ничего",
        )
        return result

    def _invalidate(self) -> None:
        """Забыть позу: после сбоя панели двигаться от неё нельзя."""
        self._pose = None


def _pose_text(pose: Pose) -> str:
    """Поза одной строкой для журнала действий."""
    return (
        f"X {pose.x:.3f} Y {pose.y:.3f} Z {pose.z:.3f} "
        f"RX {pose.rx:g} RY {pose.ry:g} RZ {pose.rz:g}"
    )
