"""Фейки окружения: ввод, буфер, панель, курсор, хранилище настроек."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping

from map_overlay.config import Settings
from map_overlay.domain.actions import Action
from map_overlay.domain.fields import Field
from map_overlay.domain.formatting import format_value
from map_overlay.domain.point import Point
from map_overlay.domain.pose import Pose


class FakeClock:
    """Запоминает паузы вместо того, чтобы спать."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class FakeClipboard:
    """Буфер обмена в памяти."""

    def __init__(self, text: str = "") -> None:
        self.text = text

    def get(self) -> str:
        return self.text

    def set(self, text: str) -> None:
        self.text = text


class FakeInput:
    """Win32 и панель в одном лице: клик по точке попадает в поле."""

    def __init__(
        self,
        *,
        clipboard: FakeClipboard,
        values: dict[Field, str],
        field_points: Mapping[Field, Point],
    ) -> None:
        self._clipboard = clipboard
        self._values = values
        self._point_to_field = {point: field for field, point in field_points.items()}
        self._cursor = Point(0, 0)
        self.clicked: list[Field] = []
        self.clicks: list[Point] = []
        self.keys: list[str] = []
        self.moved: list[Point] = []
        self.reject_paste: set[Field] = set()
        self.f_pressed = 0
        self.modifiers = 0
        """Сколько первых проверок ``modifier_down`` ответить «зажато»."""

    def modifier_down(self) -> bool:
        if self.modifiers > 0:
            self.modifiers -= 1
            return True
        return False

    @property
    def last_field(self) -> Field:
        if not self.clicked:
            raise AssertionError("Клик был не по полю панели")
        return self.clicked[-1]

    def click(self, point: Point) -> None:
        self.clicks.append(point)
        field = self._point_to_field.get(point)
        if field is not None:
            self.clicked.append(field)
        self._cursor = point

    def select_all(self) -> None:
        self.keys.append("ctrl+a")

    def copy(self) -> None:
        self.keys.append("ctrl+c")
        self._clipboard.text = self._values[self.last_field]

    def paste(self) -> None:
        self.keys.append("ctrl+v")
        if self.last_field in self.reject_paste:
            return
        self._values[self.last_field] = self._clipboard.text

    def press_f(self) -> None:
        self.keys.append("f")
        self.f_pressed += 1

    def cursor_position(self) -> Point:
        return self._cursor

    def move_cursor(self, point: Point) -> None:
        self.moved.append(point)
        self._cursor = point

    def force_cursor(self, point: Point) -> None:
        """Имитировать пользователя, который двинул мышь."""
        self._cursor = point

    def panel_value(self, field: Field) -> str:
        return self._values[field]


class FakePanel:
    """Панель LSP без мыши: значения в памяти."""

    def __init__(
        self,
        pose: Pose,
        *,
        missing: tuple[Field, ...] = (),
        decimals: int = 3,
    ) -> None:
        self.values = {field: format_value(pose.value(field), decimals) for field in Field}
        self.missing = missing
        self.reads: list[Field] = []
        self.writes: list[tuple[Field, str]] = []
        self.reject: set[Field] = set()
        self.bad_read: set[Field] = set()
        self.decimals = decimals
        self.confirm_calls = 0
        self.has_empty_point = True

    def read_field(self, field: Field) -> str:
        self.reads.append(field)
        if field in self.bad_read:
            return "не число"
        return self.values[field]

    def write_field(self, field: Field, text: str) -> None:
        self.writes.append((field, text))
        if field not in self.reject:
            self.values[field] = text

    def missing_points(self) -> tuple[Field, ...]:
        return self.missing

    def confirm(self) -> None:
        self.confirm_calls += 1

    def has_confirmation_point(self) -> bool:
        return self.has_empty_point

    @property
    def written_fields(self) -> list[Field]:
        return [field for field, _text in self.writes]

    def pose(self) -> Pose:
        return Pose(**{field.value: float(self.values[field]) for field in Field})


class FakeCursor:
    """Курсор с управляемой позицией."""

    def __init__(self, position: Point | None = None) -> None:
        self.position = position or Point(100, 200)
        self.moved: list[Point] = []

    def cursor_position(self) -> Point:
        return self.position

    def move_cursor(self, point: Point) -> None:
        self.moved.append(point)
        self.position = point


class FakeStore:
    """Хранилище настроек в памяти."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else Settings()
        self.saved: list[Settings] = []

    def load(self) -> Settings:
        return self.settings

    def save(self, settings: Settings) -> None:
        self.saved.append(settings)
        self.settings = settings


FULL_CALIBRATION: Mapping[Field, Point] = {
    Field.X: Point(100, 200),
    Field.Y: Point(300, 200),
    Field.Z: Point(500, 200),
    Field.RX: Point(100, 260),
    Field.RY: Point(300, 260),
    Field.RZ: Point(500, 260),
}


class FakeHotkeySource:
    """Горячие клавиши в памяти: тест сам «нажимает» клавиши."""

    def __init__(
        self,
        *,
        available: bool = True,
        num_lock: bool | None = True,
    ) -> None:
        self._callback: Callable[[int, bool, bool], None] | None = None
        self.bound_keys: Collection[int] = ()
        self.learning = False
        self.enabled = True
        self.frozen = False
        self.started = False
        self._available = available
        self._num_lock = num_lock
        self._down: set[int] = set()

    def start_listening(self, on_key: Callable[[int, bool, bool], None]) -> None:
        self._callback = on_key
        self.started = True

    def stop_listening(self) -> None:
        self.started = False
        self._callback = None

    def configure(self, *, bound_keys: Collection[int], learning: bool) -> None:
        self.bound_keys = frozenset(bound_keys)
        self.learning = learning

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def freeze(self, enabled: bool) -> None:
        self.frozen = enabled

    def num_lock_enabled(self) -> bool | None:
        return self._num_lock

    def is_available(self) -> bool:
        return self._available

    def key_down(self, vk: int) -> bool:
        return vk in self._down

    def press(self, vk: int, *, is_down: bool = True) -> None:
        """Имитировать нажатие клавиши.

        Автоповтор отличается так же, как в хуке: «свежее» нажатие — то, после
        которого клавишу ещё не отпускали.
        """
        if self.frozen and is_down:
            # Хук съедает нажатие: до интерфейса оно не доходит.
            return
        fresh = is_down and vk not in self._down
        if is_down:
            self._down.add(vk)
        else:
            self._down.discard(vk)
        if self._callback is not None:
            self._callback(vk, is_down, fresh)

    def release(self, vk: int) -> None:
        self.press(vk, is_down=False)

    def hold_alt(self) -> None:
        """Показать Alt физически зажатым, не посылая события: комбинация Alt+клавиша."""
        self._down.add(0x12)

    def forget(self, vk: int) -> None:
        """«Потерять» клавишу: система не прислала ``keyup``, но клавиша уже отжата."""
        self._down.discard(vk)


def bindings_of(settings: Settings) -> dict[Action, int | None]:
    return dict(settings.hotkeys)
