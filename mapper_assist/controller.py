from __future__ import annotations

from typing import Iterable

from .logger import get_logger
from .math3d import (
    TwoPointMeasurement,
    apply_local_move,
    apply_orientation_preset,
    join_next_section,
    measure_two_points,
    rotate_around_edge,
    rotate_yaw,
    snap_yaw_to_anchor,
)
from .models import FIELD_NAMES, AppSettings, MoveSpace, Transform


logger = get_logger("mapper_assist.controller")
MAX_HISTORY = 80


class MapperController:
    """
    Ядро логики приложения (без зависимости от GUI):
      - Хранит текущие координаты, историю Undo/Redo, эталон для стыковки и точки линейки A/B;
      - Отслеживает синхронизацию с полями панели игры (dirty fields), чтобы макрос вводил
        только те координаты, которые реально поменялись.
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings: AppSettings = settings or AppSettings()
        self.current: Transform = Transform()
        self.panel_synced: Transform | None = None
        self.undo_stack: list[Transform] = []
        self.redo_stack: list[Transform] = []
        self.reference_transform: Transform | None = None
        self.advance_reference_on_join: bool = True
        self.point_a: Transform | None = None
        self.point_b: Transform | None = None

    def _push_undo(self, prev: Transform) -> None:
        if self.undo_stack and self.undo_stack[-1] == prev:
            return
        self.undo_stack.append(prev)
        if len(self.undo_stack) > MAX_HISTORY:
            self.undo_stack.pop(0)

    def set_captured_transform(self, captured: Transform) -> None:
        """Обновляет состояние после чтения координат объекта из панели игры."""
        norm = captured.normalized()
        if norm != self.current:
            self._push_undo(self.current)
            self.redo_stack.clear()
        self.current = norm
        self.panel_synced = norm

    def compute_dirty_fields(self, target: Transform | None = None) -> list[str]:
        """
        Определяет, какие поля отличаются от того, что сейчас вписано в панель игры.
        Если захват ещё ни разу не делался — возвращает поля, изменившиеся относительно прошлого шага,
        либо все поля при принудительной вставке.
        """
        t = target or self.current
        if self.panel_synced is None:
            return list(FIELD_NAMES)
        return self.panel_synced.diff_fields(
            t,
            pos_decimals=self.settings.pos_decimals,
            rot_decimals=self.settings.rot_decimals,
        )

    def mark_synced(self, written_fields: Iterable[str]) -> None:
        """Помечает указанные поля как успешно записанные в панель игры."""
        fields_set = set(written_fields)
        if not fields_set:
            return
        if self.panel_synced is None:
            if fields_set == set(FIELD_NAMES):
                self.panel_synced = self.current
            return
        updated = self.panel_synced.to_dict()
        cur_dict = self.current.to_dict()
        for f in fields_set:
            if f in updated:
                updated[f] = cur_dict[f]
        self.panel_synced = Transform.from_dict(updated)

    def update_transform(self, new_transform: Transform, record_undo: bool = True) -> list[str]:
        """Применяет новую трансформацию и возвращает список изменившихся полей для панели."""
        norm = new_transform.normalized()
        prev = self.current
        if record_undo and norm != prev:
            self._push_undo(prev)
            self.redo_stack.clear()
        self.current = norm

        baseline = self.panel_synced if self.panel_synced is not None else prev
        dirty = baseline.diff_fields(
            norm,
            pos_decimals=self.settings.pos_decimals,
            rot_decimals=self.settings.rot_decimals,
        )
        logger.debug("Обновление координат: %s -> dirty=%s", norm.to_dict(), dirty)
        return dirty

    def set_single_field(self, field_name: str, value: float) -> list[str]:
        return self.update_transform(self.current.with_field(field_name, value))

    def move_step(
        self,
        right_sign: float = 0.0,
        forward_sign: float = 0.0,
        up_sign: float = 0.0,
        custom_distance: float | None = None,
    ) -> list[str]:
        dist = self.settings.step if custom_distance is None else custom_distance
        new_t = apply_local_move(
            self.current,
            right=right_sign * dist,
            forward=forward_sign * dist,
            up=up_sign * dist,
            mode=MoveSpace(self.settings.move_space),
            anchor_rz=self.settings.anchor_rz,
        )
        return self.update_transform(new_t)

    def rotate_by(self, delta_rz: float) -> list[str]:
        return self.update_transform(rotate_yaw(self.current, delta_rz))

    def snap_to_room_anchor(self, offset_deg: float = 0.0) -> list[str]:
        return self.update_transform(
            snap_yaw_to_anchor(self.current, self.settings.anchor_rz, offset_deg)
        )

    def set_anchor_from_current(self) -> float:
        self.settings.anchor_rz = self.current.rz
        return self.settings.anchor_rz

    def apply_preset(self, preset_key: str) -> list[str]:
        return self.update_transform(apply_orientation_preset(self.current, preset_key))

    def rotate_around_prop_edge(self, delta_rz: float, edge: str) -> list[str]:
        half = self.settings.prop_size / 2.0
        mapping = {
            "right": (half, 0.0),
            "left": (-half, 0.0),
            "forward": (0.0, half),
            "back": (0.0, -half),
        }
        er, ef = mapping[edge]
        return self.update_transform(rotate_around_edge(self.current, delta_rz, er, ef))

    def save_reference_from_current(self) -> Transform:
        self.reference_transform = self.current
        return self.current

    def align_to_reference(self) -> list[str]:
        """Полностью копирует координаты эталонного пропа в новый заспавненный проп."""
        if self.reference_transform is None:
            raise ValueError("Сначала сохраните эталонный объект («Запомнить эталон»)")
        # Для нового пропа в игре нужно вписать все 6 полей
        self.panel_synced = None
        self.update_transform(self.reference_transform)
        return list(FIELD_NAMES)

    def join_section_from_reference(self, direction: str, turn_deg: float = 0.0) -> list[str]:
        """
        Рассчитывает положение следующей секции от эталона (или текущего объекта)
        и при включённой опции сдвигает эталон на новую секцию для конвейерной сборки.
        """
        base = self.reference_transform if self.reference_transform is not None else self.current
        next_t = join_next_section(
            base=base,
            section_size=self.settings.prop_size,
            direction=direction,
            turn_deg=turn_deg,
        )
        self.panel_synced = None
        self.update_transform(next_t)
        if self.advance_reference_on_join:
            self.reference_transform = next_t
        return list(FIELD_NAMES)

    def set_ruler_point_a(self, t: Transform | None = None) -> Transform:
        self.point_a = (t or self.current).normalized()
        return self.point_a

    def set_ruler_point_b(self, t: Transform | None = None) -> Transform:
        self.point_b = (t or self.current).normalized()
        return self.point_b

    def get_ruler_measurement(self) -> TwoPointMeasurement | None:
        if self.point_a is None or self.point_b is None:
            return None
        return measure_two_points(self.point_a, self.point_b)

    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def undo(self) -> list[str] | None:
        if not self.undo_stack:
            return None
        prev = self.undo_stack.pop()
        self.redo_stack.append(self.current)
        baseline = self.panel_synced if self.panel_synced is not None else self.current
        self.current = prev
        return baseline.diff_fields(
            prev,
            pos_decimals=self.settings.pos_decimals,
            rot_decimals=self.settings.rot_decimals,
        )

    def redo(self) -> list[str] | None:
        if not self.redo_stack:
            return None
        nxt = self.redo_stack.pop()
        self.undo_stack.append(self.current)
        baseline = self.panel_synced if self.panel_synced is not None else self.current
        self.current = nxt
        return baseline.diff_fields(
            nxt,
            pos_decimals=self.settings.pos_decimals,
            rot_decimals=self.settings.rot_decimals,
        )
