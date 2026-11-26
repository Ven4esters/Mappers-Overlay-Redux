"""История шагов предмета: отмена и возврат (Ctrl+Z / Ctrl+Y).

История — про сдвиги по координатам, а не про правки настроек: отменить шаг значит вернуть
предмет туда, где он стоял до него. Пара замыканий «вернуть» и «повторить» описывает шаг
целиком; что именно записывается в панель, решает вызывающий код.

Модуль не знает про Qt и про панель: это обычная стопка, её проверяют без экрана.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

HISTORY_LIMIT: Final = 20
# Сколько последних шагов помним. Дальше старые вытесняются: «отменить всё» не нужно,
# а память и путаница в статусах растут.

Placement = Callable[[], bool]
# Переход «вернуть/повторить» ставит задачу и отвечает, удалось ли её начать: сама запись
# в панель идёт в фоне, поэтому об успехе узнаём позже, по колбэку окна.


@dataclass(frozen=True)
class Change:
    """Один шаг: название для строки состояния и два перехода."""

    label: str
    undo: Placement
    redo: Placement


class History:
    """Стопка последних шагов: не больше ``limit`` штук.

    Новая запись стирает «возврат»: после свежего шага повторять отменённое нельзя —
    иначе пользователь вернёт положение, которого уже не было.

    Отмена двухфазная: ``peek_undo`` показывает шаг, окно само ставит задачу, а стопки
    сдвигаются ``commit_undo`` только после успешной записи в панель. Неудачный шаг не
    теряется из истории.
    """

    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        if limit < 1:
            message = f"Предел истории должен быть положительным, получено {limit}"
            raise ValueError(message)
        self._limit = limit
        self._done: list[Change] = []
        self._undone: list[Change] = []

    def record(self, change: Change) -> None:
        """Запомнить выполненный шаг и забыть отменённые."""
        self._done.append(change)
        if len(self._done) > self._limit:
            del self._done[0 : len(self._done) - self._limit]
        self._undone.clear()

    def peek_undo(self) -> Change | None:
        """Шаг, который отменит Ctrl+Z, или ``None``."""
        return self._done[-1] if self._done else None

    def peek_redo(self) -> Change | None:
        """Шаг, который повторит Ctrl+Y, или ``None``."""
        return self._undone[-1] if self._undone else None

    def commit_undo(self) -> Change | None:
        """Зафиксировать отмену: шаг уходит в стопку возврата."""
        if not self._done:
            return None
        change = self._done.pop()
        self._undone.append(change)
        return change

    def commit_redo(self) -> Change | None:
        """Зафиксировать повтор: шаг возвращается в стопку отмены."""
        if not self._undone:
            return None
        change = self._undone.pop()
        self._done.append(change)
        return change

    def clear(self) -> None:
        """Забыть всё: например, после нового «Считать» история начинается заново."""
        self._done.clear()
        self._undone.clear()

    @property
    def can_undo(self) -> bool:
        """Есть ли что отменять."""
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        """Есть ли что повторять."""
        return bool(self._undone)

    @property
    def undo_label(self) -> str | None:
        """Название шага, который отменит Ctrl+Z."""
        return self._done[-1].label if self._done else None

    @property
    def redo_label(self) -> str | None:
        """Название шага, который повторит Ctrl+Y."""
        return self._undone[-1].label if self._undone else None

    def __len__(self) -> int:
        """Сколько шагов можно отменить прямо сейчас."""
        return len(self._done)
