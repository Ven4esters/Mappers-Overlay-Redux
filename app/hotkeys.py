"""Global hotkeys (Windows) with native event filter. / Глобальные хоткеи (Windows).

Actions: ``fullscreen`` (Ctrl+Shift+S) and ``region`` (Ctrl+Shift+R).
On non-Windows platforms ``supported()`` returns False and the manager is a no-op;
in-app Ctrl+Shift+S / Ctrl+Shift+R shortcuts still work inside the window.
На не-Windows платформах менеджер неактивен; горячие клавиши внутри окна работают всегда.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312
MOD_CONTROL, MOD_SHIFT = 0x0002, 0x0004
VK_S, VK_R = 0x53, 0x52
FULLSCREEN_ID, REGION_ID = 0xB10, 0xB11


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, handler) -> None:
        super().__init__()
        self._handler = handler

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt naming)
        if str(eventType) == "windows_generic_MSG":
            import ctypes
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                which = {FULLSCREEN_ID: "fullscreen", REGION_ID: "region"}.get(int(msg.wParam))
                if which:
                    self._handler(which)
        return False, 0


class HotkeyManager(QObject):
    """Registers/unregisters global hotkeys; emits ``actionRequested``.
    Регистрирует глобальные хоткеи; эмитит ``actionRequested('fullscreen'|'region')``."""

    actionRequested = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._filter: _HotkeyEventFilter | None = None

    @staticmethod
    def supported() -> bool:
        return sys.platform.startswith("win")

    def install(self, app) -> bool:
        if not self.supported():
            return False
        import ctypes

        user32 = ctypes.windll.user32
        ok_full = user32.RegisterHotKey(None, FULLSCREEN_ID, MOD_CONTROL | MOD_SHIFT, VK_S)
        ok_region = user32.RegisterHotKey(None, REGION_ID, MOD_CONTROL | MOD_SHIFT, VK_R)
        self._filter = _HotkeyEventFilter(self.actionRequested.emit)
        app.installNativeEventFilter(self._filter)
        return bool(ok_full) and bool(ok_region)

    def shutdown(self) -> None:
        if not self.supported() or self._filter is None:
            return
        import ctypes

        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, FULLSCREEN_ID)
        user32.UnregisterHotKey(None, REGION_ID)
        self._filter = None
