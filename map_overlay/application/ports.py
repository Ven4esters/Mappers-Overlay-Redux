"""Порты: что приложению нужно от окружения. Реализации — в ``infrastructure``."""

from __future__ import annotations

from collections.abc import Callable, Collection
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

    def has_confirmation_point(self) -> bool:
        """Задана ли точка для клика перед клавишей F."""
        ...

    def confirm(self) -> None:
        """Кликнуть в пустое место панели и нажать F."""
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

    def press_f(self) -> None:
        """Нажать ``F`` (подтверждение положения в редакторе)."""
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


class HotkeySource(Protocol):
    """Глобальные горячие клавиши."""

    def start_listening(self, on_key: Callable[[int, bool], None]) -> None:
        """Начать слушать клавиатуру; ``on_key`` получает код клавиши и нажатие/отпускание."""
        ...

    def stop_listening(self) -> None:
        """Перестать слушать клавиатуру."""
        ...

    def configure(self, *, bound_keys: Collection[int], learning: bool) -> None:
        """Сказать источнику, какие клавиши перехватывать и идёт ли запись новой привязки."""
        ...

    def set_enabled(self, enabled: bool) -> None:
        """Включить или приостановить перехват (аварийный выход для игры)."""
        ...

    def num_lock_enabled(self) -> bool | None:
        """Включён ли NumLock (``None``, если проверить нельзя)."""
        ...

    def alt_down(self) -> bool:
        """Зажат ли Alt: с ним шаг идёт по наклону ``RX``."""
        ...

    def key_down(self, vk: int) -> bool:
        """Зажата ли клавиша прямо сейчас (страховка на случай потерянного ``keyup``)."""
        ...

    def is_available(self) -> bool:
        """Удалось ли перехватывать клавиши."""
        ...


class SettingsStore(Protocol):
    """Хранилище настроек."""

    def load(self) -> Settings:
        """Загрузить настройки (или значения по умолчанию)."""
        ...

    def save(self, settings: Settings) -> None:
        """Сохранить настройки."""
        ...
