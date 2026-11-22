"""Инфраструктура: Windows API, буфер обмена, файлы настроек."""

from lsp_overlay.infrastructure.clipboard import ClipboardPort, SystemClipboard
from lsp_overlay.infrastructure.config_store import ConfigStore, default_config_path
from lsp_overlay.infrastructure.panel import ClipboardPanel
from lsp_overlay.infrastructure.win32_input import InputBackend, Win32InputBackend

__all__ = [
    "ClipboardPanel",
    "ClipboardPort",
    "ConfigStore",
    "InputBackend",
    "SystemClipboard",
    "Win32InputBackend",
    "default_config_path",
]
