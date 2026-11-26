"""Системный буфер обмена через ``pyperclip``."""

from __future__ import annotations

import pyperclip

from map_overlay.errors import ClipboardError


class SystemClipboard:
    """Реализация :class:`map_overlay.application.ports.ClipboardPort`."""

    def get(self) -> str:
        """Прочитать текст буфера."""
        try:
            text = pyperclip.paste()
        except pyperclip.PyperclipException as exc:
            raise ClipboardError(f"Буфер обмена недоступен: {exc}") from exc
        return text if isinstance(text, str) else ""

    def set(self, text: str) -> None:
        """Положить текст в буфер."""
        try:
            pyperclip.copy(text)
        except pyperclip.PyperclipException as exc:
            raise ClipboardError(f"Не удалось записать в буфер обмена: {exc}") from exc
