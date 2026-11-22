"""Инфраструктура: Windows API, буфер обмена, файлы настроек."""

from lsp_overlay.infrastructure.clipboard import ClipboardPort, SystemClipboard
from lsp_overlay.infrastructure.config_store import ConfigStore, default_config_path
from lsp_overlay.infrastructure.global_keys import NullKeyHook, Win32KeyHook
from lsp_overlay.infrastructure.panel import ClipboardPanel
from lsp_overlay.infrastructure.win32_input import (
    InputBackend,
    NullKeyState,
    Win32InputBackend,
    Win32KeyState,
)

__all__ = [
    "ClipboardPanel",
    "ClipboardPort",
    "ConfigStore",
    "InputBackend",
    "NullKeyHook",
    "NullKeyState",
    "SystemClipboard",
    "Win32InputBackend",
    "Win32KeyHook",
    "Win32KeyState",
    "default_config_path",
]
