from __future__ import annotations

import pyperclip

from .base import InputBackend


class FallbackInputBackend(InputBackend):
    """Запасной кроссплатформенный бэкенд для не-Windows окружений и тестирования."""

    def __init__(self) -> None:
        self._cursor = (0, 0)
        self._clip = ""

    def get_cursor_pos(self) -> tuple[int, int]:
        return self._cursor

    def set_cursor_pos(self, x: int, y: int) -> None:
        self._cursor = (int(x), int(y))

    def left_click(self, x: int, y: int) -> None:
        self._cursor = (int(x), int(y))

    def send_ctrl_Combo(self, letter: str) -> None:
        pass

    def send_enter(self) -> None:
        pass

    def wait_modifiers_released(self, timeout_ms: int = 320) -> None:
        pass

    def ensure_window_at_point_focused(
        self,
        x: int,
        y: int,
        neutral_point: tuple[int, int] | None,
        settle_ms: int,
    ) -> None:
        pass

    def get_clipboard(self) -> str:
        try:
            return pyperclip.paste() or ""
        except Exception:  # noqa: BLE001
            return self._clip

    def set_clipboard(self, text: str) -> None:
        self._clip = text
        try:
            pyperclip.copy(text)
        except Exception:  # noqa: BLE001
            pass
