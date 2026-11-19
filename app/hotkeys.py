"""Global hotkeys (Windows) with native event filter. / Глобальные хоткеи (Windows).

Actions: ``overlay`` (PrintScreen — открыть выбор режима), ``fullscreen`` (Ctrl+Shift+S),
``region`` (Ctrl+Shift+R).
On non-Windows platforms ``supported()`` returns False and the manager is a no-op;
an in-app QShortcut for PrintScreen still works inside the window.
На не-Windows платформах менеджер неактивен; внутри окна PrintScreen работает всегда.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312
MOD_CONTROL, MOD_SHIFT, MOD_NONE = 0x0002, 0x0004, 0x0000
VK_S, VK_R, VK_SNAPSHOT = 0x53, 0x52, 0x2C
FULLSCREEN_ID, REGION_ID, OVERLAY_ID = 0xB10, 0xB11, 0xB12


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, handler) -> None:
        super().__init__()
        self._handler = handler

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt naming)
        if str(eventType) == "windows_generic_MSG":
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                which = {FULLSCREEN_ID: "fullscreen", REGION_ID: "region",
                         OVERLAY_ID: "overlay"}.get(int(msg.wParam))
                if which:
                    self._handler(which)
        return False, 0


class HotkeyManager(QObject):
    """Registers/unregisters global hotkeys; emits ``actionRequested``.
    Регистрирует глобальные хоткеи; эмитит ``actionRequested('fullscreen'|'region')``."""

    actionRequested = Signal(str)  # "overlay" | "fullscreen" | "region"

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
        ok_overlay = user32.RegisterHotKey(None, OVERLAY_ID, MOD_NONE, VK_SNAPSHOT)
        self._filter = _HotkeyEventFilter(self.actionRequested.emit)
        app.installNativeEventFilter(self._filter)
        return bool(ok_full) and bool(ok_region) and bool(ok_overlay)

    def shutdown(self) -> None:
        if not self.supported() or self._filter is None:
            return
        import ctypes

        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, FULLSCREEN_ID)
        user32.UnregisterHotKey(None, REGION_ID)
        user32.UnregisterHotKey(None, OVERLAY_ID)
        self._filter = None
