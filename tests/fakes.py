"""Фейки окружения: ввод, буфер, панель, курсор, хранилище настроек."""

from __future__ import annotations

from collections.abc import Mapping

from map_overlay.config import Settings
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
        self.keys: list[str] = []
        self.moved: list[Point] = []
        self.reject_paste: set[Field] = set()

    @property
    def last_field(self) -> Field:
        return self.clicked[-1]

    def click(self, point: Point) -> None:
        field = self._point_to_field.get(point)
        if field is None:
            raise AssertionError(f"Клик мимо поля панели: {point}")
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
