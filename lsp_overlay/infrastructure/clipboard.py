"""Работа с системным буфером обмена.

Буфер может быть занят игрой, поэтому установка текста повторяется несколько раз.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import pyperclip

LOGGER = logging.getLogger(__name__)

COPY_ATTEMPTS = 5
COPY_PAUSE = 0.02


class ClipboardError(RuntimeError):
    """Не удалось прочитать или записать буфер обмена."""


class ClipboardPort(Protocol):
    """Контракт буфера обмена."""

    def get_text(self) -> str:
        """Текущий текст буфера (пустая строка, если он пуст)."""

    def set_text(self, text: str) -> None:
        """Кладёт текст в буфер."""


class SystemClipboard:
    """Обёртка над ``pyperclip`` с повторами на случай занятого буфера."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._sleep = sleep

    def get_text(self) -> str:
        """Читает текст из буфера обмена."""
        for attempt in range(COPY_ATTEMPTS):
            try:
                return str(pyperclip.paste())
            except Exception as error:  # pyperclip кидает разные исключения платформ
                LOGGER.debug("Не удалось прочитать буфер (попытка %s): %s", attempt + 1, error)
                self._sleep(COPY_PAUSE)
        raise ClipboardError("буфер обмена недоступен для чтения")

    def set_text(self, text: str) -> None:
        """Записывает текст в буфер обмена с повторами."""
        for attempt in range(COPY_ATTEMPTS):
            try:
                pyperclip.copy(text)
                return
            except Exception as error:
                LOGGER.debug("Не удалось записать буфер (попытка %s): %s", attempt + 1, error)
                self._sleep(COPY_PAUSE)
        raise ClipboardError("буфер обмена недоступен для записи")
