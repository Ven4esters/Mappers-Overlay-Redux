"""История правок: отмена и возврат последних действий (Ctrl+Z / Ctrl+Y).

Модуль не знает про Qt и про то, что именно отменяется: действие описывается парой
замыканий «как отменить» и «как вернуть». Такая пара — снимок состояния модели
(библиотека размеров или настройки), поэтому отмена не зависит от того, каким путём
правку сделали.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

HISTORY_LIMIT: Final = 20
# Сколько последних действий помним. Дальше старые вытесняются: «отменить всё» не нужно,
# а память и путаница в статусах растут.


@dataclass(frozen=True)
class Change:
    """Одно действие: название для строки состояния и два перехода."""

    label: str
    undo: Callable[[], None]
    redo: Callable[[], None]


class History:
    """Стопка последних действий: не больше ``limit`` штук.

    Новая запись стирает «возврат»: после свежей правки возвращать отменённое нельзя —
    иначе пользователь вернёт состояние, которого уже не было.
    """

    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        if limit < 1:
            message = f"Предел истории должен быть положительным, получено {limit}"
            raise ValueError(message)
        self._limit = limit
        self._done: list[Change] = []
        self._undone: list[Change] = []

    def record(self, change: Change) -> None:
        """Запомнить выполненное действие и забыть отменённые."""
        self._done.append(change)
        if len(self._done) > self._limit:
            del self._done[0 : len(self._done) - self._limit]
        self._undone.clear()

    def undo(self) -> str | None:
        """Отменить последнее действие и вернуть его название.

        Returns:
            Название отменённого действия или ``None``, если отменять нечего.

        Raises:
            Exception: любое исключение из перехода «отменить»; стопка при этом не меняется,
                чтобы действие не потерялось.
        """
        if not self._done:
            return None
        change = self._done[-1]
        change.undo()
        self._done.pop()
        self._undone.append(change)
        return change.label

    def redo(self) -> str | None:
        """Вернуть отменённое действие и вернуть его название.

        Returns:
            Название возвращённого действия или ``None``, если возвращать нечего.
        """
        if not self._undone:
            return None
        change = self._undone[-1]
        change.redo()
        self._undone.pop()
        self._done.append(change)
        return change.label

    def clear(self) -> None:
        """Забыть всё: например, после загрузки другого профиля."""
        self._done.clear()
        self._undone.clear()

    @property
    def can_undo(self) -> bool:
        """Есть ли что отменять."""
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        """Есть ли что возвращать."""
        return bool(self._undone)

    @property
    def undo_label(self) -> str | None:
        """Название действия, которое отменит Ctrl+Z."""
        return self._done[-1].label if self._done else None

    @property
    def redo_label(self) -> str | None:
        """Название действия, которое вернёт Ctrl+Y."""
        return self._undone[-1].label if self._undone else None

    def __len__(self) -> int:
        """Сколько действий можно отменить прямо сейчас."""
        return len(self._done)
