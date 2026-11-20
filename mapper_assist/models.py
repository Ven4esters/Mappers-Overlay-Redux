from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .formatting import clean_zero, format_number, normalize_angle_180, parse_number  # noqa: F401


FIELD_NAMES: tuple[str, ...] = ("x", "y", "z", "rx", "ry", "rz")
POS_FIELDS: tuple[str, ...] = ("x", "y", "z")
ROT_FIELDS: tuple[str, ...] = ("rx", "ry", "rz")

CALIBRATION_TARGETS: tuple[str, ...] = ("x", "y", "z", "rx", "ry", "rz", "neutral")

CALIBRATION_LABELS: dict[str, str] = {
    "x": "Поле X (Координата)",
    "y": "Поле Y (Координата)",
    "z": "Поле Z (Высота)",
    "rx": "Поле RX (Наклон вперёд/назад)",
    "ry": "Поле RY (Крен влево/вправо)",
    "rz": "Поле RZ (Поворот вокруг оси Z)",
    "neutral": "Точка мимо полей (Сброс фокуса + Enter)",
}


class MoveSpace(str, Enum):
    """Система координат для сдвига объекта."""

    OBJECT_HORIZONTAL = "object_horizontal"  # По углу RZ объекта параллельно полу (основной)
    ANCHOR_HORIZONTAL = "anchor_horizontal"  # По базовому углу комнаты (якорю)
    OBJECT_3D = "object_3d"                  # Полный 3D с учётом наклона RX/RY/RZ
    WORLD = "world"                          # Мировые оси GTA V (+X Восток, +Y Север, +Z Верх)


@dataclass(frozen=True)
class Transform:
    """Положение и ориентация объекта в GTA V (углы в градусах [-180, 180])."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0

    def normalized(self) -> Transform:
        return Transform(
            x=clean_zero(self.x),
            y=clean_zero(self.y),
            z=clean_zero(self.z),
            rx=normalize_angle_180(self.rx),
            ry=normalize_angle_180(self.ry),
            rz=normalize_angle_180(self.rz),
        )

    def get_field(self, name: str) -> float:
        if name not in FIELD_NAMES:
            raise KeyError(f"Неизвестное поле трансформации: {name}")
        return float(getattr(self, name))

    def with_field(self, name: str, value: float) -> Transform:
        if name not in FIELD_NAMES:
            raise KeyError(f"Неизвестное поле трансформации: {name}")
        data = self.to_dict()
        data[name] = normalize_angle_180(value) if name in ROT_FIELDS else clean_zero(value)
        return Transform(**data)

    def diff_fields(
        self,
        other: Transform,
        pos_decimals: int = 4,
        rot_decimals: int = 3,
    ) -> list[str]:
        """Возвращает список только тех полей, строковое представление которых реально изменилось."""
        changed: list[str] = []
        for fname in FIELD_NAMES:
            dec = rot_decimals if fname in ROT_FIELDS else pos_decimals
            s1 = format_number(self.get_field(fname), decimals=dec)
            s2 = format_number(other.get_field(fname), decimals=dec)
            if s1 != s2:
                changed.append(fname)
        return changed

    def format_field(
        self,
        name: str,
        pos_decimals: int = 4,
        rot_decimals: int = 3,
        strip_trailing_zeros: bool = True,
    ) -> str:
        dec = rot_decimals if name in ROT_FIELDS else pos_decimals
        return format_number(self.get_field(name), decimals=dec, strip_trailing_zeros=strip_trailing_zeros)

    def to_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "rx": self.rx,
            "ry": self.ry,
            "rz": self.rz,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transform:
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            z=float(data.get("z", 0.0)),
            rx=float(data.get("rx", 0.0)),
            ry=float(data.get("ry", 0.0)),
            rz=float(data.get("rz", 0.0)),
        ).normalized()


@dataclass
class Point2D:
    x: int
    y: int

    def to_tuple(self) -> tuple[int, int]:
        return (int(self.x), int(self.y))


@dataclass
class CalibrationProfile:
    """Экранные координаты полей левой панели LSP и точки сброса фокуса."""

    points: dict[str, Point2D | None] = field(
        default_factory=lambda: {target: None for target in CALIBRATION_TARGETS}
    )

    def get_point(self, target: str) -> Point2D | None:
        return self.points.get(target)

    def set_point(self, target: str, x: int, y: int) -> None:
        if target not in CALIBRATION_TARGETS:
            raise KeyError(f"Неизвестная точка калибровки: {target}")
        self.points[target] = Point2D(int(x), int(y))

    def is_basic_ready(self) -> bool:
        """Минимум для горизонтальной работы: X, Y, Z, RZ."""
        return all(self.points.get(k) is not None for k in ("x", "y", "z", "rz"))

    def is_full_ready(self) -> bool:
        """Все 6 полей + точка клика мимо полей."""
        return all(self.points.get(k) is not None for k in CALIBRATION_TARGETS)

    def missing_targets(self) -> list[str]:
        return [k for k in CALIBRATION_TARGETS if self.points.get(k) is None]

    def to_dict(self) -> dict[str, dict[str, int] | None]:
        out: dict[str, dict[str, int] | None] = {}
        for k in CALIBRATION_TARGETS:
            pt = self.points.get(k)
            out[k] = {"x": pt.x, "y": pt.y} if pt is not None else None
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> CalibrationProfile:
        profile = cls()
        if not raw:
            return profile
        for k in CALIBRATION_TARGETS:
            item = raw.get(k)
            if isinstance(item, dict) and "x" in item and "y" in item:
                profile.points[k] = Point2D(int(item["x"]), int(item["y"]))
        return profile


@dataclass
class MacroTimings:
    """Тайминги кликов и буфера обмена (в миллисекундах)."""

    click_delay_ms: int = 25
    key_delay_ms: int = 20
    focus_handoff_ms: int = 55
    clipboard_timeout_ms: int = 180
    save_enter_delay_ms: int = 35

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> MacroTimings:
        if not raw:
            return cls()
        defaults = cls()
        return cls(
            click_delay_ms=max(5, int(raw.get("click_delay_ms", defaults.click_delay_ms))),
            key_delay_ms=max(5, int(raw.get("key_delay_ms", defaults.key_delay_ms))),
            focus_handoff_ms=max(10, int(raw.get("focus_handoff_ms", defaults.focus_handoff_ms))),
            clipboard_timeout_ms=max(40, int(raw.get("clipboard_timeout_ms", defaults.clipboard_timeout_ms))),
            save_enter_delay_ms=max(10, int(raw.get("save_enter_delay_ms", defaults.save_enter_delay_ms))),
        )


@dataclass
class HotkeyConfig:
    """Глобальные горячие клавиши (по умолчанию без конфликта с F8-консолью FiveM и F-меню сервера)."""

    capture: str = "Alt+C"
    save_commit: str = "Alt+S"
    paste_all: str = "Alt+B"
    calibrate_point: str = "F9"
    move_forward: str = "Alt+Up"
    move_back: str = "Alt+Down"
    move_left: str = "Alt+Left"
    move_right: str = "Alt+Right"
    move_up: str = "Alt+PageUp"
    move_down: str = "Alt+PageDown"
    rot_left_90: str = "Alt+Q"
    rot_right_90: str = "Alt+E"
    undo: str = "Alt+Z"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> HotkeyConfig:
        if not raw:
            return cls()
        defaults = cls()
        kwargs = {k: str(raw.get(k, getattr(defaults, k))) for k in asdict(defaults)}
        return cls(**kwargs)


@dataclass
class AppSettings:
    """Полный профиль настроек приложения, сохраняемый между сессиями."""

    step: float = 0.1
    angle_step: float = 90.0
    prop_size: float = 2.0
    anchor_rz: float = 0.0
    move_space: str = MoveSpace.OBJECT_HORIZONTAL.value
    auto_apply_to_game: bool = True
    auto_save_enter: bool = False
    unfocus_after_paste: bool = False
    fast_capture_skip_tilt: bool = False
    always_on_top: bool = True
    window_opacity: float = 0.95
    pos_decimals: int = 4
    rot_decimals: int = 3
    hotkeys_enabled: bool = True
    step_presets: list[float] = field(
        default_factory=lambda: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0]
    )
    saved_prop_sizes: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"name": "Анти-щель (5 мм)", "size": 0.005},
            {"name": "Малый шаг (10 см)", "size": 0.1},
            {"name": "Стандарт 1 м", "size": 1.0},
            {"name": "Секция 2 м", "size": 2.0},
        ]
    )
    # --- Поправки направлений (если оси на конкретном сервере/сборке инвертированы) ---
    invert_forward: bool = False
    invert_right: bool = False
    invert_up: bool = False
    invert_rotate: bool = False
    # --- Защита от «улёта» объекта ---
    safe_write_verify: bool = True   # перечитывать поля после вставки и сравнивать
    max_jump: float = 20.0           # максимально допустимый скачок за один ввод, метры
    calibration: CalibrationProfile = field(default_factory=CalibrationProfile)
    timings: MacroTimings = field(default_factory=MacroTimings)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "angle_step": self.angle_step,
            "prop_size": self.prop_size,
            "anchor_rz": self.anchor_rz,
            "move_space": self.move_space,
            "auto_apply_to_game": self.auto_apply_to_game,
            "auto_save_enter": self.auto_save_enter,
            "unfocus_after_paste": self.unfocus_after_paste,
            "fast_capture_skip_tilt": self.fast_capture_skip_tilt,
            "always_on_top": self.always_on_top,
            "window_opacity": self.window_opacity,
            "pos_decimals": self.pos_decimals,
            "rot_decimals": self.rot_decimals,
            "hotkeys_enabled": self.hotkeys_enabled,
            "invert_forward": self.invert_forward,
            "invert_right": self.invert_right,
            "invert_up": self.invert_up,
            "invert_rotate": self.invert_rotate,
            "safe_write_verify": self.safe_write_verify,
            "max_jump": self.max_jump,
            "step_presets": list(self.step_presets),
            "saved_prop_sizes": list(self.saved_prop_sizes),
            "calibration": self.calibration.to_dict(),
            "timings": self.timings.to_dict(),
            "hotkeys": self.hotkeys.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AppSettings:
        if not raw:
            return cls()
        defaults = cls()
        move_space = str(raw.get("move_space", defaults.move_space))
        valid_spaces = {m.value for m in MoveSpace}
        if move_space not in valid_spaces:
            move_space = defaults.move_space

        presets_raw = raw.get("step_presets", defaults.step_presets)
        presets = [float(x) for x in presets_raw] if isinstance(presets_raw, list) and presets_raw else defaults.step_presets

        saved_sizes_raw = raw.get("saved_prop_sizes", defaults.saved_prop_sizes)
        saved_sizes = saved_sizes_raw if isinstance(saved_sizes_raw, list) else defaults.saved_prop_sizes

        return cls(
            step=max(0.0001, float(raw.get("step", defaults.step))),
            angle_step=float(raw.get("angle_step", defaults.angle_step)),
            prop_size=max(0.001, float(raw.get("prop_size", defaults.prop_size))),
            anchor_rz=normalize_angle_180(float(raw.get("anchor_rz", defaults.anchor_rz))),
            move_space=move_space,
            auto_apply_to_game=bool(raw.get("auto_apply_to_game", defaults.auto_apply_to_game)),
            auto_save_enter=bool(raw.get("auto_save_enter", defaults.auto_save_enter)),
            unfocus_after_paste=bool(raw.get("unfocus_after_paste", defaults.unfocus_after_paste)),
            fast_capture_skip_tilt=bool(raw.get("fast_capture_skip_tilt", defaults.fast_capture_skip_tilt)),
            always_on_top=bool(raw.get("always_on_top", defaults.always_on_top)),
            window_opacity=min(1.0, max(0.4, float(raw.get("window_opacity", defaults.window_opacity)))),
            pos_decimals=min(6, max(1, int(raw.get("pos_decimals", defaults.pos_decimals)))),
            rot_decimals=min(6, max(1, int(raw.get("rot_decimals", defaults.rot_decimals)))),
            hotkeys_enabled=bool(raw.get("hotkeys_enabled", defaults.hotkeys_enabled)),
            invert_forward=bool(raw.get("invert_forward", defaults.invert_forward)),
            invert_right=bool(raw.get("invert_right", defaults.invert_right)),
            invert_up=bool(raw.get("invert_up", defaults.invert_up)),
            invert_rotate=bool(raw.get("invert_rotate", defaults.invert_rotate)),
            safe_write_verify=bool(raw.get("safe_write_verify", defaults.safe_write_verify)),
            max_jump=max(1.0, float(raw.get("max_jump", defaults.max_jump))),
            step_presets=presets,
            saved_prop_sizes=saved_sizes,
            calibration=CalibrationProfile.from_dict(raw.get("calibration")),
            timings=MacroTimings.from_dict(raw.get("timings")),
            hotkeys=HotkeyConfig.from_dict(raw.get("hotkeys")),
        )
