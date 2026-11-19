from __future__ import annotations

import time
from typing import Iterable

from ..formatting import parse_number
from ..logger import get_logger
from ..models import (
    CALIBRATION_LABELS,
    FIELD_NAMES,
    CalibrationProfile,
    MacroTimings,
    Transform,
)
from .base import AutomationError, InputBackend


logger = get_logger("mapper_assist.automation.panel")
_CLIPBOARD_SENTINEL = "__LSP_MAPPER_READ__"


class PanelAutomator:
    """
    Высокоуровневый сценарий взаимодействия с левой панелью координат Los Santos Project:
      - Чтение полей через клик -> Ctrl+A -> Ctrl+C с защитой от старого буфера;
      - Точечная вставка только изменившихся полей через клик -> Ctrl+A -> Ctrl+V;
      - Фиксация/сохранение: клик ЛКМ мимо поля (neutral) + нажатие Enter;
      - Подробное логирование времени выполнения и диагностика ошибок чтения/записи.
    """

    def __init__(self, backend: InputBackend) -> None:
        self.backend = backend

    def get_cursor_pos(self) -> tuple[int, int]:
        return self.backend.get_cursor_pos()

    def _require_points(
        self,
        calibration: CalibrationProfile,
        targets: Iterable[str],
    ) -> dict[str, tuple[int, int]]:
        resolved: dict[str, tuple[int, int]] = {}
        missing: list[str] = []
        for t in targets:
            pt = calibration.get_point(t)
            if pt is None:
                missing.append(CALIBRATION_LABELS.get(t, t))
            else:
                resolved[t] = pt.to_tuple()
        if missing:
            msg = "Не откалиброваны точки экрана: " + ", ".join(missing)
            logger.warning(msg)
            raise AutomationError(msg)
        return resolved

    def read_transform(
        self,
        calibration: CalibrationProfile,
        timings: MacroTimings,
        skip_tilt: bool = False,
        base_transform: Transform | None = None,
    ) -> Transform:
        """Считывает координаты выделенного объекта из левой панели редактора."""
        t0 = time.perf_counter()
        fields_to_read = ("x", "y", "z", "rz") if skip_tilt else FIELD_NAMES
        coords = self._require_points(calibration, fields_to_read)
        neutral_pt = calibration.get_point("neutral")
        neutral_tuple = neutral_pt.to_tuple() if neutral_pt else None

        logger.info("Начало захвата полей %s из панели игры...", fields_to_read)
        orig_cursor = self.backend.get_cursor_pos()
        try:
            orig_clip = self.backend.get_clipboard()
        except AutomationError:
            orig_clip = ""

        self.backend.wait_modifiers_released()

        first_pt = coords[fields_to_read[0]]
        self.backend.ensure_window_at_point_focused(
            first_pt[0],
            first_pt[1],
            neutral_tuple,
            timings.focus_handoff_ms,
        )

        values: dict[str, float] = (base_transform or Transform()).to_dict()
        if skip_tilt:
            values["rx"] = 0.0
            values["ry"] = 0.0

        try:
            for fname in fields_to_read:
                px, py = coords[fname]
                raw_val = self._read_single_field(fname, px, py, timings)
                try:
                    values[fname] = parse_number(raw_val)
                    logger.debug("Поле '%s' (%d, %d): raw=%r -> %f", fname, px, py, raw_val, values[fname])
                except ValueError as exc:
                    label = CALIBRATION_LABELS.get(fname, fname)
                    logger.error(
                        "Ошибка распознавания числа в поле '%s' по координатам (%d, %d): raw=%r",
                        fname,
                        px,
                        py,
                        raw_val,
                    )
                    raise AutomationError(
                        f"Не удалось прочитать число из «{label}» (получено: {raw_val!r}). "
                        f"Проверьте, открыта ли панель объекта и верна ли калибровка."
                    ) from exc

            if neutral_tuple is not None:
                self.backend.left_click(neutral_tuple[0], neutral_tuple[1])
                time.sleep(timings.click_delay_ms / 1000.0)
        finally:
            try:
                self.backend.set_clipboard(orig_clip)
            except AutomationError:
                pass
            self.backend.set_cursor_pos(orig_cursor[0], orig_cursor[1])

        result = Transform.from_dict(values)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "Захват успешно завершён за %.1f мс: X=%.4f, Y=%.4f, Z=%.4f, RX=%.3f, RY=%.3f, RZ=%.3f",
            elapsed_ms,
            result.x,
            result.y,
            result.z,
            result.rx,
            result.ry,
            result.rz,
        )
        return result

    def _read_single_field(self, fname: str, px: int, py: int, timings: MacroTimings) -> str:
        for attempt in range(2):
            self.backend.set_clipboard(_CLIPBOARD_SENTINEL)
            self.backend.left_click(px, py)
            time.sleep(timings.click_delay_ms / 1000.0)

            self.backend.send_ctrl_Combo("A")
            time.sleep(timings.key_delay_ms / 1000.0)
            self.backend.send_ctrl_Combo("C")

            deadline = time.monotonic() + (timings.clipboard_timeout_ms / 1000.0)
            while time.monotonic() < deadline:
                time.sleep(0.006)
                clip = self.backend.get_clipboard()
                if clip != _CLIPBOARD_SENTINEL and clip.strip() != "":
                    return clip

            if attempt == 0:
                logger.warning(
                    "Таймаут чтения буфера (%d мс) на поле '%s' (%d, %d) — повторная попытка...",
                    timings.clipboard_timeout_ms,
                    fname,
                    px,
                    py,
                )
                time.sleep(0.025)

        return self.backend.get_clipboard()

    def write_fields(
        self,
        transform: Transform,
        fields: Iterable[str],
        calibration: CalibrationProfile,
        timings: MacroTimings,
        pos_decimals: int = 4,
        rot_decimals: int = 3,
        unfocus_after: bool = False,
        save_with_enter: bool = False,
    ) -> list[str]:
        """Вставляет указанные поля (Ctrl+A -> Ctrl+V) и при необходимости сохраняет (Клик мимо + Enter)."""
        t0 = time.perf_counter()
        ordered_fields = [f for f in FIELD_NAMES if f in set(fields)]
        if not ordered_fields and not save_with_enter:
            return []

        required = list(ordered_fields)
        if save_with_enter or unfocus_after:
            required.append("neutral")
        coords = self._require_points(calibration, required)

        neutral_pt = calibration.get_point("neutral")
        neutral_tuple = neutral_pt.to_tuple() if neutral_pt else None

        logger.info(
            "Запись полей %s в панель (save_with_enter=%s, unfocus_after=%s)",
            ordered_fields,
            save_with_enter,
            unfocus_after,
        )

        orig_cursor = self.backend.get_cursor_pos()
        try:
            orig_clip = self.backend.get_clipboard()
        except AutomationError:
            orig_clip = ""

        self.backend.wait_modifiers_released()

        first_target = ordered_fields[0] if ordered_fields else "neutral"
        first_pt = coords[first_target]
        self.backend.ensure_window_at_point_focused(
            first_pt[0],
            first_pt[1],
            neutral_tuple,
            timings.focus_handoff_ms,
        )

        try:
            for fname in ordered_fields:
                px, py = coords[fname]
                formatted = transform.format_field(
                    fname,
                    pos_decimals=pos_decimals,
                    rot_decimals=rot_decimals,
                )
                logger.debug("Вставка в поле '%s' (%d, %d) значения '%s'", fname, px, py, formatted)
                self.backend.set_clipboard(formatted)
                self.backend.left_click(px, py)
                time.sleep(timings.click_delay_ms / 1000.0)

                self.backend.send_ctrl_Combo("A")
                time.sleep(timings.key_delay_ms / 1000.0)
                self.backend.send_ctrl_Combo("V")
                time.sleep(timings.key_delay_ms / 1000.0)

            if save_with_enter:
                nx, ny = coords["neutral"]
                logger.debug("Фиксация сохранения: клик в neutral (%d, %d) + Enter", nx, ny)
                self.backend.left_click(nx, ny)
                time.sleep(timings.save_enter_delay_ms / 1000.0)
                self.backend.send_enter()
                time.sleep(timings.key_delay_ms / 1000.0)
            elif unfocus_after and "neutral" in coords:
                nx, ny = coords["neutral"]
                self.backend.left_click(nx, ny)
                time.sleep(timings.click_delay_ms / 1000.0)
        finally:
            time.sleep(0.020)
            try:
                self.backend.set_clipboard(orig_clip)
            except AutomationError:
                pass
            self.backend.set_cursor_pos(orig_cursor[0], orig_cursor[1])

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info("Запись полей %s завершена за %.1f мс", ordered_fields, elapsed_ms)
        return ordered_fields

    def commit_save_only(
        self,
        calibration: CalibrationProfile,
        timings: MacroTimings,
    ) -> None:
        """Клик ЛКМ мимо поля (neutral) + нажатие Enter для сохранения введённых координат."""
        coords = self._require_points(calibration, ["neutral"])
        nx, ny = coords["neutral"]
        orig_cursor = self.backend.get_cursor_pos()

        logger.info("Команда сохранения объекта: клик мимо полей (%d, %d) + Enter", nx, ny)
        self.backend.wait_modifiers_released()
        self.backend.ensure_window_at_point_focused(
            nx,
            ny,
            (nx, ny),
            timings.focus_handoff_ms,
        )
        try:
            self.backend.left_click(nx, ny)
            time.sleep(timings.save_enter_delay_ms / 1000.0)
            self.backend.send_enter()
            time.sleep(timings.key_delay_ms / 1000.0)
        finally:
            self.backend.set_cursor_pos(orig_cursor[0], orig_cursor[1])
