"""Реальные паузы между шагами обмена с панелью."""

from __future__ import annotations

import time


class SystemClock:
    """Реализация :class:`map_overlay.application.ports.Clock`."""

    def sleep(self, seconds: float) -> None:
        """Подождать указанное время."""
        if seconds > 0:
            time.sleep(seconds)
