from __future__ import annotations

import sys

from ..logger import get_logger
from .base import AutomationError, InputBackend
from .fallback_backend import FallbackInputBackend
from .panel_automator import PanelAutomator as _BasePanelAutomator
from .win32_backend import WIN32_INPUT, Win32InputBackend


logger = get_logger("mapper_assist.automation")


def create_default_backend() -> InputBackend:
    if sys.platform == "win32":
        return Win32InputBackend()
    logger.info("Платформа '%s' (не Windows): используется тестовый FallbackInputBackend", sys.platform)
    return FallbackInputBackend()


class PanelAutomator(_BasePanelAutomator):
    def __init__(self, backend: InputBackend | None = None) -> None:
        super().__init__(backend=backend or create_default_backend())


__all__ = [
    "AutomationError",
    "FallbackInputBackend",
    "InputBackend",
    "PanelAutomator",
    "WIN32_INPUT",
    "Win32InputBackend",
    "create_default_backend",
]
