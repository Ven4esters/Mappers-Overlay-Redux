"""Движение предмета: «Считать», шаги, вставка, удержание клавиши, история.

Здесь сценарии, которые меняют координаты: захват позы, шаг по направлению, вставка
в панель, подтверждение клавишей ``F``, удержание направления и отмена шага. Всё, что
не меняет позу (раскладка, занятость, клавиатура), живёт в соседних частях."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import cast

from map_overlay.application.history import Change, History
from map_overlay.application.session import MappingSession, PasteResult, StepResult
from map_overlay.domain.actions import Action
from map_overlay.domain.directions import Direction
from map_overlay.domain.fields import Field
from map_overlay.domain.formatting import format_delta, format_value
from map_overlay.domain.keynames import VK_MENU, key_name
from map_overlay.domain.movement import COORD_DECIMALS
from map_overlay.domain.pose import Pose
from map_overlay.domain.sizes import SizeLibrary
from map_overlay.errors import ConfigError, ValidationError
from map_overlay.trace import note
from map_overlay.ui.tabs.movement_tab import pose_text
from map_overlay.ui.window_base import (
    HOLD_REPEAT_MS,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_WARN,
    WindowBase,
)

logger = logging.getLogger(__name__)


class WindowMovementMixin(WindowBase):
    """Часть окна: см. описание модуля, состояние — в ``WindowBase``."""

    def _sizes_changed(self, library: object) -> None:
        """Сохранить библиотеку размеров и обновить список предметов."""
        candidate = cast(SizeLibrary, library)
        if not self._apply_library(candidate):
            return
        active = candidate.active_item
        suffix = f", выбран «{active.name}»" if active is not None else ""
        self._set_status(f"Размеры: предметов {len(candidate.items)}{suffix}", STATUS_OK)

    def _apply_library(self, library: SizeLibrary) -> bool:
        """Записать библиотеку в файл и показать её в обеих вкладках.

        Returns:
            ``True``, если файл записался; иначе в строке состояния уже ошибка.
        """
        try:
            self._context.save_sizes(library)
        except ConfigError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            return False
        self.sizes.set_library(library)
        self.movement.set_sizes(library)
        return True

    def _size_selected(self, name: object) -> None:
        """Запомнить выбранный предмет: из него берётся шаг."""
        selected = cast("str | None", name)
        previous = self._context.sizes
        try:
            library = previous.select(selected)
        except ValidationError as exc:
            self._set_status(str(exc), STATUS_ERROR)
            self.movement.set_sizes(previous)
            return
        if not self._apply_library(library):
            self.movement.set_sizes(previous)
            return
        active = library.active_item
        if active is None:
            self._set_status("Предмет не выбран: шаг задаётся вручную.")
            return
        self._set_status(
            f"Выбран «{active.name}»: длина, ширина и половины подставляются в шаг кнопками.",
            STATUS_OK,
        )

    def _capture(self) -> None:
        note("команда: считать координаты")
        self._stop_hold()
        if self._runner.is_busy():
            note("считать не начато: занято «%s»", self._busy_text)
            return
        session = self._ensure_session()
        self._begin_busy("Читаю поля панели…")
        self._runner.submit(
            session.capture,
            on_success=self._captured,
            on_error=self._failed,
            label="считать координаты",
        )

    def _paste(self, source: Pose | None = None) -> bool:
        """Вписать считанные координаты и углы в тот предмет, что открыт в панели.

        Источник — поза из карточки «Координаты и углы»: та, что снята кнопкой «Считать»
        и с тех пор сдвинута шагами. ``F`` вставка не нажимает: предмет встаёт на место,
        когда пользователь подтвердит его сам.

        Returns:
            ``True``, если задача поставлена; ``False`` — вставлять нечего или занято.
        """
        self._stop_hold()
        if self._runner.is_busy():
            logger.info("Вставка не начата: занято «%s»", self._busy_text)
            note("вставка не начата: занято «%s»", self._busy_text)
            self._set_status(
                f"Дождитесь окончания действия: «{self._busy_text}» ещё идёт.", STATUS_WARN
            )
            return False
        origin = self._pose if source is None else source
        if origin is None:
            logger.warning("Вставка не начата: координаты не считаны")
            note("вставка не начата: координаты не считаны")
            self._set_status("Сначала нажмите «Считать»: вставлять пока нечего", STATUS_WARN)
            return False
        session = self._ensure_session()
        note("команда: вставить координаты")
        self._begin_busy("Вставляю координаты и углы в текущий предмет…")
        self._runner.submit(
            lambda: session.paste(origin),
            on_success=self._pasted,
            on_error=self._failed,
            label="вставить координаты",
        )
        return True

    def _confirm(self) -> None:
        note("команда: сохранить F")
        self._stop_hold()
        if self._runner.is_busy():
            note("сохранить F не начато: занято «%s»", self._busy_text)
            return
        session = self._ensure_session()
        self._begin_busy("Подтверждаю положение: клик в пустое место и F…")
        self._runner.submit(
            session.confirm,
            on_success=self._confirmed,
            on_error=self._failed,
            label="сохранить F",
        )

    def _move(
        self,
        direction: object,
        step: float,
        *,
        tilt: bool = False,
        straight: bool | None = None,
        refresh: bool | None = None,
    ) -> bool:
        """Сделать шаг; ``tilt`` — режим высоты (клавиша Alt): 8 вверх, 2 вниз.

        ``straight`` — «Прямой шаг 4/6/8/2»: при наклоне клавиши 4/6/8/2 идут по мировым
        осям, высота — строго по ``Z``. ``None`` означает «как включено в режиме»: так
        приходят нажатия кнопок крестовины, а удержание клавиши передаёт текущее значение.

        ``refresh`` — прочитать поля панели перед шагом (режим «Всегда считать позицию»):
        шаг считается от свежих координат, поэтому «Считать» заранее не нужно. ``None``
        означает «как включено в режиме»: так приходят нажатия кнопок крестовины, а
        удержание клавиши передаёт ``False`` со второго шага, чтобы не читать поля зря.

        Returns:
            ``True``, если задача поставлена: ``False`` — шаг невозможен.
        """
        refresh = self._always_read if refresh is None else refresh
        straight = self._straight if straight is None else straight
        if self._step_is_blocked(refresh):
            return False
        session = self._ensure_session()
        selected = cast(Direction, direction)
        suffix = self._height_suffix(selected, tilt)
        busy = f"Шаг {selected.label} на {step:g} м{suffix}"
        self._begin_busy(f"{busy}…" if not refresh else f"{busy}: сначала читаю позицию…")
        self._last_request = (selected, step, tilt, straight)
        self._submit_step(session, selected, step, tilt, straight, refresh, suffix)
        return True

    def _step_is_blocked(self, refresh: bool) -> bool:
        """Почему шаг нельзя начать: занято или координаты не считаны."""
        if self._runner.is_busy():
            logger.info("Шаг не начат: занято другим действием")
            note("шаг не начат: занято другим действием")
            return True
        pose = self._pose
        if refresh or (self._session is not None and self._session.pose is not None and pose):
            return False
        logger.warning("Шаг не начат: координаты не считаны")
        note("шаг не начат: координаты не считаны")
        self._set_status("Сначала нажмите «Считать»: без координат шаг не посчитать", STATUS_WARN)
        return True

    def _height_suffix(self, direction: Direction, tilt: bool) -> str:
        """Пометка шага в высоте: «(вверх)»/«(вниз)» — чтобы в статусе было видно, почему."""
        if not tilt or direction not in (Direction.FORWARD, Direction.BACK):
            return ""
        return " (вверх)" if direction is Direction.FORWARD else " (вниз)"

    def _submit_step(
        self,
        session: MappingSession,
        direction: Direction,
        step: float,
        tilt: bool,
        straight: bool,
        refresh: bool,
        suffix: str,
    ) -> None:
        """Поставить задачу шага: с чтением позиции перед ним или без."""
        label = f"шаг {direction.label.lower()} на {step:g} м{suffix}"
        if refresh:
            self._runner.submit(
                lambda: session.capture_and_step(direction, step, tilt=tilt, straight=straight),
                on_success=self._moved,
                on_error=self._failed,
                label=label,
            )
            return
        self._runner.submit(
            lambda: session.step(direction, step, tilt=tilt, straight=straight),
            on_success=self._moved,
            on_error=self._failed,
            label=label,
        )

    def _captured(self, result: object) -> None:
        self._set_busy(False)
        # Новый «Считать» начинает новый отрезок: отменять шаги от прежних координат нельзя.
        self._history.clear()
        pose = cast(Pose, result)
        self._pose = pose
        self.movement.set_pose(pose)
        self.movement.set_warning(self._tilt_warning(pose))
        self._set_status(f"Считано: {pose_text(pose)}", STATUS_OK)

    def _moved(self, result: object) -> None:
        self._set_busy(False)
        self._schedule_hold_step()
        step_result = cast(StepResult, result)
        self._pose = step_result.pose
        self.movement.set_pose(step_result.pose)
        self.movement.set_warning(self._tilt_warning(step_result.pose))
        written = ", ".join(field.label for field in step_result.written) or "ничего"
        deltas = f"ΔX {format_delta(step_result.delta_x)} · ΔY {format_delta(step_result.delta_y)}"
        slope = ""
        if step_result.delta_z:
            deltas = f"{deltas} · ΔZ {format_delta(step_result.delta_z)}"
        if step_result.tilted:
            slope = " · Alt: вверх/вниз"
        if step_result.reread:
            slope = f"{slope} · позиция считана заново"
        prefix = self._commit_history(self._step_change(step_result))
        self._set_status(
            f"{prefix}Шаг: {deltas} → {pose_text(step_result.pose)} · записано: {written}{slope}",
            STATUS_OK,
        )

    def _pasted(self, result: object) -> None:
        """Итог вставки: показать новую позу и запомнить её в истории."""
        self._set_busy(False)
        paste_result = cast(PasteResult, result)
        self._pose = paste_result.pose
        self.movement.set_pose(paste_result.pose)
        self.movement.set_warning(self._tilt_warning(paste_result.pose))
        change: Change | None = None
        if paste_result.changed:
            previous = paste_result.previous
            source = paste_result.pose
            change = Change(
                "перенос координат",
                lambda: self._restore_pose(previous, full=True),
                lambda: self._paste(source),
            )
        prefix = self._commit_history(change)
        if not paste_result.changed:
            self._set_status(
                f"{prefix}У получателя уже эти координаты: писать нечего.", STATUS_WARN
            )
            return
        written = ", ".join(field.label for field in paste_result.written)
        self._set_status(
            f"{prefix}Вставлено: {pose_text(paste_result.pose)} · записано: {written}. "
            "Нажмите F, чтобы применить.",
            STATUS_OK,
        )

    def _step_change(self, step_result: StepResult) -> Change | None:
        """Описание шага для истории; ``None`` — шаг поставлен не направлением (отмена)."""
        request = self._last_request
        self._last_request = None
        if request is None:
            return None
        direction, step, tilt, straight = request
        return Change(
            self._step_label(direction, step, tilt=tilt),
            lambda: self._restore_pose(step_result.previous),
            lambda: self._repeat_step(direction, step, tilt=tilt, straight=straight),
        )

    def _commit_history(self, change: Change | None) -> str:
        """Закрепить отмену/повтор или запомнить новый шаг; вернуть префикс для статуса."""
        kind = self._pending_kind
        pending = self._pending_change
        self._pending_kind = None
        self._pending_change = None
        if kind == "undo" and pending is not None:
            self._history.commit_undo()
            logger.info("Отменён шаг: %s", pending.label)
            return f"Отменён {pending.label}. "
        if kind == "redo" and pending is not None:
            self._history.commit_redo()
            logger.info("Повторён шаг: %s", pending.label)
            return f"Повторён {pending.label}. "
        if change is not None:
            self._history.record(change)
        return ""

    def _step_label(self, direction: Direction, step: float, *, tilt: bool = False) -> str:
        """Название шага для строки состояния: «шаг «Вперёд» на 0.5 м»."""
        suffix = " (высота)" if tilt else ""
        return f"шаг «{direction.label}» на {step:g} м{suffix}"

    def _restore_pose(self, pose: Pose, *, full: bool = False) -> bool:
        """Отменить изменение: вернуть координаты (или всю позу при ``full``), что были до него."""
        if not self._check_step_ready("отменять шаг"):
            return False
        session = self._session
        if session is None:
            return False
        self._begin_busy("Отменяю изменение: возвращаю координаты…")
        self._runner.submit(
            lambda: session.restore(pose, full=full),
            on_success=self._moved,
            on_error=self._failed,
            label="отмена шага",
        )
        return True

    def _repeat_step(
        self,
        direction: Direction,
        step: float,
        *,
        tilt: bool = False,
        straight: bool | None = None,
    ) -> bool:
        """Повторить шаг: тот же сдвиг от текущей позы."""
        return self._move(direction, step, tilt=tilt, straight=straight)

    def _confirmed(self, _result: object) -> None:
        self._set_busy(False)
        self._set_status("Положение подтверждено клавишей F", STATUS_OK)

    def _failed(self, message: str) -> None:
        logger.warning("Действие не выполнено: %s", message)
        self._stop_hold()
        self._set_busy(False)
        # Неудачный шаг не попадает в историю и не сдвигает стопки: отменять нечего.
        self._pending_kind = None
        self._pending_change = None
        self._last_request = None
        if self._session is not None and self._session.pose is None:
            self._drop_pose(message)
            message = f"{message}. Нажмите «Считать» и повторите"
        self._set_status(message, STATUS_ERROR)

    def _tilt_warning(self, pose: Pose) -> str:
        """Подсказка про режим высоты: только когда он выключен и предмет наклонён."""
        if self._tilt_mode or not pose.has_tilt:
            return ""
        angles = " · ".join(
            f"{field.value.upper()} {format_value(pose.value(field), COORD_DECIMALS)}°"
            for field in (Field.RX, Field.RY)
            if abs(pose.value(field)) > 1e-9
        )
        if self._straight:
            return (
                f"{angles}: «Прямой шаг 4/6/8/2» — клавиши 4/6/8/2 идут по мировым осям. "
                "Нажмите Alt — Num 8 поднимет предмет строго вверх, Num 2 опустит."
            )
        return (
            f"{angles}: нажмите Alt — Num 8 будет поднимать предмет, Num 2 опускать. "
            "Сейчас они идут вперёд и назад."
        )

    def _refresh_tilt_warning(self) -> None:
        """Подсказка про режим высоты зависит от того, включён он или нет."""
        pose = self._pose
        self.movement.set_warning("" if pose is None else self._tilt_warning(pose))

    def _toggle_tilt(self) -> None:
        """Переключить режим высоты: Alt нажимают один раз, а не держат.

        Держать Alt нельзя: пока он зажат, игра не применяет правки панели к
        объекту — значения доходят до интерфейса и теряются.
        """
        self._set_tilt(not self._tilt_mode)

    def _set_tilt(self, enabled: bool) -> None:
        if enabled == self._tilt_mode:
            return
        self._tilt_mode = enabled
        note("режим высоты: %s", "включён" if enabled else "выключен")
        self.movement.set_tilt(enabled)
        self._refresh_tilt_warning()
        if enabled:
            logger.info("Режим высоты включён")
            self._set_status(
                "Режим высоты включён: Num 8 — вверх, Num 2 — вниз. Остальные клавиши "
                "работают как обычно. Alt — выключить.",
                STATUS_OK,
            )
        else:
            logger.info("Режим высоты выключен")
            self._set_status("Режим высоты выключен: Num 8 — вперёд, Num 2 — назад.")

    def _set_straight(self, enabled: bool) -> None:
        """Включить «Прямой шаг 4/6/8/2» и запомнить выбор.

        Переключатель касается только клавиш ``Num 4/6/8/2`` и режима высоты: при наклоне
        предмета они идут по мировым осям, без формул поворота. Диагонали считаются по
        формулам как обычно. Позу и историю переключение не трогает — это настройка
        движения, а не новые координаты. Выбор живёт в `config/settings.json`.
        """
        if enabled == self._straight:
            self.movement.set_straight(enabled)
            return
        self._straight = enabled
        self.movement.set_straight(enabled)
        settings = replace(self._context.settings, straight_cardinal=enabled)
        try:
            self._context.save_settings(settings)
        except ConfigError as exc:
            self._straight = False
            self.movement.set_straight(False)
            self._set_status(str(exc), STATUS_ERROR)
            return
        # Настройки на вкладке «Настройки» держат свою копию: без этого «Сохранить» там
        # вернуло бы прежнее значение режима.
        self.settings_tab.set_base_settings(settings)
        self._refresh_tilt_warning()
        if enabled:
            note("режим «прямой шаг 4/6/8/2» включён")
            logger.info("Режим «Прямой шаг 4/6/8/2» включён")
            self._set_status(
                "«Прямой шаг 4/6/8/2» включён: при RX/RY ≠ 0 клавиши 4/6/8/2 двигают предмет "
                "по мировым осям, Alt+8/2 — строго по Z. Диагонали — по формулам.",
                STATUS_OK,
            )
            return
        note("режим «прямой шаг 4/6/8/2» выключен")
        logger.info("Режим «Прямой шаг 4/6/8/2» выключен")
        self._set_status(
            "«Прямой шаг 4/6/8/2» выключен: шаг снова считается по формулам поворота.",
        )

    def _set_always_read(self, enabled: bool) -> None:
        """Включить или выключить режим «Всегда считать позицию» и запомнить выбор.

        Режим живёт в `config/settings.json`: включённый однажды, он остаётся включённым
        после перезапуска. Позу и историю переключение не трогает — это настройка движения,
        а не новые координаты.
        """
        if enabled == self._always_read:
            self.movement.set_always_read(enabled)
            return
        self._always_read = enabled
        self.movement.set_always_read(enabled)
        settings = replace(self._context.settings, always_read_pose=enabled)
        try:
            self._context.save_settings(settings)
        except ConfigError as exc:
            self._always_read = False
            self.movement.set_always_read(False)
            self._set_status(str(exc), STATUS_ERROR)
            return
        # Настройки на вкладке «Настройки» держат свою копию: без этого «Сохранить» там
        # вернуло бы прежнее значение режима.
        self.settings_tab.set_base_settings(settings)
        if enabled:
            note("режим «всегда считать позицию» включён")
            logger.info("Режим «Всегда считать позицию» включён")
            self._set_status(
                "Режим «Всегда считать позицию» включён: перед каждым нажатием направления "
                "оверлей сам читает поля панели. «Считать» заранее не нужно.",
                STATUS_OK,
            )
            return
        note("режим «всегда считать позицию» выключен")
        logger.info("Режим «Всегда считать позицию» выключен")
        self._set_status(
            "Режим «Всегда считать позицию» выключен: шаг считается от считанных координат.",
        )

    def _start_hold(self, action: Action, vk: int) -> None:
        """Начать удержание: первый шаг сразу, следующие — друг за другом.

        В режиме «Всегда считать позицию» поля читаются один раз, на первом шаге нажатия:
        повторные шаги идут от позы, которую оверлей только что записал. Читать перед
        каждым шагом удержания значило бы удвоить паузу между шагами.
        """
        self._stop_hold()
        self._refresh_on_step = self._always_read
        self._held = (action, vk)
        note("удержание: %s (клавиша %s)", action.label, key_name(vk))
        self._hold_tick(force=True)

    def _hold_tick(self, *, force: bool = False) -> None:
        """Сделать очередной шаг удержания.

        ``force`` — вызов из самого нажатия: событие уже доказывает, что клавишу
        нажали, поэтому состояние клавиши не перепроверяется. Без этого быстрое
        нажатие не давало шага вовсе.

        Следующий шаг ставится не по общему таймеру, а после завершения текущего
        (:meth:`_schedule_hold_step`): один шаг занимает около секунды, и обмен
        с панелью сам задаёт темп — движение идёт без пауз и рывков.
        """
        held = self._held
        if held is None:
            self._hold_timer.stop()
            return
        action, vk = held
        if not self.settings_tab.hotkeys_enabled():
            self._stop_hold()
            return
        if not force and not self._hotkeys.key_down(vk):
            logger.debug("Удержание %s снято: клавиша не нажата", action.label)
            self._stop_hold()
            return
        if force and self._hotkeys.key_down(VK_MENU):
            logger.warning(
                "Alt зажат во время шага: игра может не применить изменение. "
                "Режим высоты включается одним нажатием Alt"
            )
        if self._runner.is_busy():
            return
        if not self._step_once(action):
            self._stop_hold()

    def _schedule_hold_step(self) -> None:
        """Поставить следующий шаг удержания сразу после завершения текущего."""
        if self._held is not None:
            self._hold_timer.start(HOLD_REPEAT_MS)

    def _step_once(self, action: Action) -> bool:
        direction = action.direction
        if direction is None:
            return False
        try:
            step = self.movement.current_step()
        except ValidationError as exc:
            logger.warning("Шаг не начат: %s", exc)
            self._set_status(str(exc), STATUS_WARN)
            return False
        # Чтение перед шагом — только для первого шага нажатия, дальше поза уже свежая.
        refresh = self._refresh_on_step
        self._refresh_on_step = False
        return self._move(
            direction, step, tilt=self._tilt_mode, straight=self._straight, refresh=refresh
        )

    def _release_key(self, vk: int) -> None:
        """Отпускание клавиши прекращает удержание."""
        if self._held is not None and self._held[1] == vk:
            self._stop_hold()

    def _stop_hold(self) -> None:
        self._refresh_on_step = False
        if self._held is not None:
            note("удержание остановлено: %s", self._held[0].label)
        self._hold_timer.stop()
        self._held = None

    def history(self) -> History:
        """История правок (Ctrl+Z / Ctrl+Y): нужна строке состояния и тестам."""
        return self._history

    def undo(self) -> bool:
        """Отменить последний шаг: вернуть предмет туда, где он стоял (Ctrl+Z).

        Returns:
            ``True``, если задача поставлена; итог записи придёт колбэком шага.
        """
        self._stop_hold()
        ready = self._check_step_ready("отменять шаг")
        if not ready:
            return False
        change = self._history.peek_undo()
        if change is None:
            self._set_status("Отменять нечего: шагов после «Считать» не было.", STATUS_WARN)
            return False
        # Задачу ставим после того, как запомнили, что это отмена: при синхронном
        # выполнении колбэк шага придёт прямо из change.undo().
        self._pending_kind = "undo"
        self._pending_change = change
        if not change.undo():
            self._pending_kind = None
            self._pending_change = None
            return False
        note("отмена шага: %s", change.label)
        return True

    def redo(self) -> bool:
        """Повторить отменённый шаг (Ctrl+Y).

        Шаг повторяется тем же направлением, шагом и режимом высоты: сдвиг считается
        от текущей позы, поэтому предмет встаёт туда же, где стоял.

        Returns:
            ``True``, если задача поставлена.
        """
        self._stop_hold()
        ready = self._check_step_ready("повторять шаг")
        if not ready:
            return False
        change = self._history.peek_redo()
        if change is None:
            self._set_status("Повторять нечего: отменённых шагов нет.", STATUS_WARN)
            return False
        self._pending_kind = "redo"
        self._pending_change = change
        if not change.redo():
            self._pending_kind = None
            self._pending_change = None
            return False
        note("повтор шага: %s", change.label)
        return True
