"""Тестовые двойники портов и эмулятор панели LSP."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from lsp_overlay.application.errors import PanelUnavailableError
from lsp_overlay.config import Calibration, Point
from lsp_overlay.domain.fields import FieldKey, get_field
from lsp_overlay.domain.pose import Pose


class FakeGamePanel:
    """Панель игры в памяти: хранит значения полей и записывает историю."""

    def __init__(self, pose: Pose | None = None, *, available: bool = True) -> None:
        self.pose = pose or Pose()
        self.available = available
        self.writes: list[dict[FieldKey, float]] = []
        self.commits = 0
        self.reads = 0
        self.fail_write = False
        self.ignore_fields: set[FieldKey] = set()
        self.ignore_once_fields: set[FieldKey] = set()
        self.keys: list[str] = []
        self.read_fields_calls: list[tuple[FieldKey, ...]] = []

    def is_available(self) -> bool:
        return self.available

    def configure(
        self,
        *,
        calibration: Calibration,
        timings: object,
        length_decimals: int,
        confirm_key: str,
    ) -> None:
        self.calibration = calibration
        self.length_decimals = length_decimals
        self.confirm_key = confirm_key

    def read_pose(self) -> Pose:
        if not self.available:
            raise PanelUnavailableError("панель недоступна")
        self.reads += 1
        return self.pose

    def read_fields(self, keys: Sequence[FieldKey]) -> dict[FieldKey, float]:
        if not self.available:
            raise PanelUnavailableError("панель недоступна")
        self.reads += 1
        self.read_fields_calls.append(tuple(keys))
        return {key: get_field(self.pose, key) for key in keys}

    def write_fields(self, values: Mapping[FieldKey, float]) -> None:
        if self.fail_write:
            raise PanelUnavailableError("не удалось записать поле")
        self.writes.append(dict(values))
        resolved = {key: key.value for key in FieldKey}
        updated = {name: getattr(self.pose, name) for key, name in resolved.items()}
        for key, value in values.items():
            if key in self.ignore_fields:
                continue
            if key in self.ignore_once_fields:
                self.ignore_once_fields.discard(key)
                continue
            updated[resolved[key]] = value
        self.pose = Pose(**updated)

    def commit(self) -> None:
        if not self.available:
            raise PanelUnavailableError("панель недоступна")
        self.commits += 1

    def tap_key(self, key: str) -> None:
        if not self.available:
            raise PanelUnavailableError("панель недоступна")
        self.keys.append(key)


class FakeInput:
    """Записывает события ввода и умеет «водить мышью» по эмулятору игры."""

    def __init__(self, game: FakeLspGame | None = None, *, ready: bool = True) -> None:
        self.events: list[tuple[str, str]] = []
        self.ready = ready
        self.game = game
        self.needs_activation = False
        self.cursor: tuple[int, int] | None = None
        self.cursor_drift: tuple[int, int] | None = None

    def is_ready(self) -> bool:
        return self.ready

    def ensure_foreground(self, x: int, y: int) -> bool:
        self.events.append(("focus", f"{x},{y}"))
        return self.needs_activation

    def press_combination(self, *keys: str) -> None:
        combination = "+".join(keys)
        self.events.append(("combo", combination))
        if self.game is not None:
            self.game.handle_combo(combination)

    def tap_key(self, key: str) -> None:
        self.events.append(("key", key))
        if self.game is not None:
            self.game.handle_key(key)

    def click(self, x: int, y: int) -> None:
        self.events.append(("click", f"{x},{y}"))
        self.cursor = (x, y)
        if self.game is not None:
            self.game.handle_click(x, y)

    def cursor_position(self) -> tuple[int, int] | None:
        if self.cursor_drift is not None:
            # имитация: руку положили на мышь и курсор уехал
            return self.cursor_drift
        return self.cursor


class FakeClipboard:
    """Буфер обмена в памяти."""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.queue: list[str] = []
        self.lazy_polls = 0
        self._last_set = ""

    def get_text(self) -> str:
        if self.lazy_polls > 0:
            # имитация: Ctrl+C ещё не дошёл, в буфере лежит прежнее значение
            self.lazy_polls -= 1
            return self._last_set
        return self.queue.pop(0) if self.queue else self.text

    def set_text(self, text: str) -> None:
        self.text = text
        self._last_set = text


class FakeLspGame:
    """Эмулятор левой панели LSP: клики, Ctrl+A/C/V и подтверждение клавишей.

    Позволяет воспроизводить реальные дефекты: ``drop_select_all=True`` имитирует
    ситуацию, когда ``Ctrl+A`` не сработал и значение дописалось к старому.
    """

    def __init__(
        self,
        calibration: Calibration,
        pose: Pose,
        clipboard: FakeClipboard,
        *,
        confirm_key: str = "f",
        drop_select_all: bool = False,
    ) -> None:
        self.calibration = calibration
        self.pose = pose
        self.clipboard = clipboard
        self.confirm_key = confirm_key
        self.drop_select_all = drop_select_all
        self.focused: FieldKey | None = None
        self.selection: str | None = None
        self.commits = 0
        self.last_confirm_key: str | None = None

    def _point_to_field(self) -> dict[tuple[int, int], FieldKey]:
        return {point.as_tuple(): key for key, point in self.calibration.fields.items()}

    def handle_click(self, x: int, y: int) -> None:
        self.focused = self._point_to_field().get((x, y))
        self.selection = None

    def handle_combo(self, combination: str) -> None:
        if self.focused is None:
            return
        if combination == "ctrl+a":
            self.selection = None if self.drop_select_all else self._field_text()
        elif combination == "ctrl+c":
            self.clipboard.text = self.selection if self.selection is not None else ""
        elif combination == "ctrl+v":
            pasted = self.clipboard.text
            new_text = pasted if self.selection is not None else f"{self._field_text()}{pasted}"
            self._set_field_text(new_text)
            self.selection = None

    def handle_key(self, key: str) -> None:
        if key.lower() == self.confirm_key and self.focused is None:
            self.commits += 1
            self.last_confirm_key = key

    def _field_text(self) -> str:
        assert self.focused is not None
        return f"{get_field(self.pose, self.focused):.4f}"

    def _set_field_text(self, text: str) -> None:
        assert self.focused is not None
        try:
            value = float(text.replace("°", "").strip())
        except ValueError:
            return  # игра игнорирует мусор
        self.pose = Pose(
            **{
                **{key.value: getattr(self.pose, key.value) for key in FieldKey},
                self.focused.value: value,
            }
        )


def build_calibration() -> Calibration:
    """Калибровка из шести полей и «пустого места» для тестов интерфейса."""
    calibration = Calibration.empty()
    for index, key in enumerate(FieldKey):
        calibration = calibration.with_point(key, Point(x=100, y=200 + index * 30))
    return calibration.with_placeholder(Point(x=900, y=900))


class FakeKeyState:
    """Состояние клавиш в памяти: какие виртуальные коды «зажаты»."""

    def __init__(self, *, ready: bool = True, num_lock: bool = True) -> None:
        self.ready = ready
        self.num_lock = num_lock
        self.down: set[int] = set()

    def is_ready(self) -> bool:
        return self.ready

    def is_down(self, vk_code: int) -> bool:
        return vk_code in self.down

    def num_lock_enabled(self) -> bool:
        return self.num_lock


class FakeKeyHook:
    """Хук в памяти: запоминает подписку и позволяет «нажать» клавишу из теста."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.callback: Callable[[int, bool], None] | None = None
        self.started = 0

    def is_available(self) -> bool:
        return self.available

    def start(self, callback: Callable[[int, bool], None]) -> bool:
        if not self.available:
            return False
        self.callback = callback
        self.started += 1
        return True

    def stop(self) -> None:
        self.callback = None

    def press(self, vk_code: int) -> None:
        """Нажатие перехваченной клавиши."""
        self._send(vk_code, pressed=True)

    def release(self, vk_code: int) -> None:
        """Отпускание перехваченной клавиши."""
        self._send(vk_code, pressed=False)

    def _send(self, vk_code: int, *, pressed: bool) -> None:
        if self.callback is None:
            raise AssertionError("хук не поставлен")
        self.callback(vk_code, pressed)
