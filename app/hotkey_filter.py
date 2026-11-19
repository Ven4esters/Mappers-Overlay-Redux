"""Native event filter for the RegisterHotKey fallback. / Фильтр WM_HOTKEY.

Split out so ``app.hotkeys`` stays importable without instantiating Qt
machinery — the low-level hook path doesn't need this at all.
Вынесен отдельно, чтобы fallback-путь на WM_HOTKEY жил без Qt-зависимости
основного модуля; low-level hook в нём не нуждается.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
FULLSCREEN_ID, REGION_ID, OVERLAY_ID = 0xB10, 0xB11, 0xB12


class HotkeyEventFilter(QAbstractNativeEventFilter):
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
