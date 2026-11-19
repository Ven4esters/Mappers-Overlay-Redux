from __future__ import annotations

from abc import ABC, abstractmethod


class AutomationError(RuntimeError):
    """Ошибка чтения/вставки координат в игровую панель."""


class InputBackend(ABC):
    """Абстракция ввода мыши, клавиатуры и буфера обмена (реальная ОС или тестовый мок)."""

    @abstractmethod
    def get_cursor_pos(self) -> tuple[int, int]:
        raise NotImplementedError

    @abstractmethod
    def set_cursor_pos(self, x: int, y: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def left_click(self, x: int, y: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_ctrl_Combo(self, letter: str) -> None:
        """Отправляет Ctrl + A / C / V."""
        raise NotImplementedError

    @abstractmethod
    def send_enter(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def wait_modifiers_released(self, timeout_ms: int = 320) -> None:
        raise NotImplementedError

    @abstractmethod
    def ensure_window_at_point_focused(
        self,
        x: int,
        y: int,
        neutral_point: tuple[int, int] | None,
        settle_ms: int,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_clipboard(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def set_clipboard(self, text: str) -> None:
        raise NotImplementedError
