"""Порты: что приложению нужно от окружения. Реализации — в ``infrastructure``."""

from __future__ import annotations

from typing import Protocol

from map_overlay.config import Settings
from map_overlay.domain.fields import Field
from map_overlay.domain.point import Point


class PanelAutomation(Protocol):
    """Обмен с панелью LSP через клики и буфер обмена."""

    def read_field(self, field: Field) -> str:
        """Прочитать текст поля."""
        ...

    def write_field(self, field: Field, text: str) -> None:
        """Вставить текст в поле."""
        ...

    def missing_points(self) -> tuple[Field, ...]:
        """Поля без точки калибровки."""
        ...


class InputPort(Protocol):
    """Клавиатура и мышь Windows."""

    def click(self, point: Point) -> None:
        """Навести курсор в точку и кликнуть левой кнопкой."""
        ...

    def select_all(self) -> None:
        """``Ctrl+A``."""
        ...

    def copy(self) -> None:
        """``Ctrl+C``."""
        ...

    def paste(self) -> None:
        """``Ctrl+V``."""
        ...

    def cursor_position(self) -> Point:
        """Текущая позиция курсора."""
        ...

    def move_cursor(self, point: Point) -> None:
        """Переместить курсор без клика."""
        ...


class CursorPort(Protocol):
    """Только курсор: нужен калибровке."""

    def cursor_position(self) -> Point:
        """Текущая позиция курсора."""
        ...

    def move_cursor(self, point: Point) -> None:
        """Переместить курсор без клика."""
        ...


class ClipboardPort(Protocol):
    """Системный буфер обмена."""

    def get(self) -> str:
        """Текущий текст буфера."""
        ...

    def set(self, text: str) -> None:
        """Положить текст в буфер."""
        ...


class Clock(Protocol):
    """Паузы между шагами обмена."""

    def sleep(self, seconds: float) -> None:
        """Подождать указанное время."""
        ...


class SettingsStore(Protocol):
    """Хранилище настроек."""

    def load(self) -> Settings:
        """Загрузить настройки (или значения по умолчанию)."""
        ...

    def save(self, settings: Settings) -> None:
        """Сохранить настройки."""
        ...
