"""Global hotkeys (Windows) with native event filter. / Глобальные хоткеи (Windows).

Default bindings: PrintScreen (``overlay`` — открывает выбор режима),
Ctrl+Shift+S (``fullscreen``), Ctrl+Shift+R (``region``).
The overlay hotkey is user-configurable (Win+PrtSc and plain PrtSc are often
taken by Windows/Snipping Tool) — see ``AppSettings.capture_hotkey``.

On non-Windows platforms ``supported()`` returns False and the manager is a
no-op; the in-window bindings for the same combos still work.
На не-Windows платформах менеджер неактивен; внутри окна те же комбинации
работают всегда.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from app.hotkey_parse import DEFAULT_HOTKEY, normalize_hotkey, to_windows

logger = logging.getLogger("screensaver.hotkeys")

WM_HOTKEY = 0x0312
MOD_CONTROL, MOD_SHIFT = 0x0002, 0x0004
VK_S, VK_R = 0x53, 0x52
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
    Регистрирует глобальные хоткеи; эмитит ``actionRequested(...)``."""

    actionRequested = Signal(str)  # "overlay" | "fullscreen" | "region"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._filter: _HotkeyEventFilter | None = None
        self._capture_combo: str = DEFAULT_HOTKEY

    @staticmethod
    def supported() -> bool:
        return sys.platform.startswith("win")

    @staticmethod
    def capture_hotkey(capture_hotkey: str) -> str:
        """Effective, guaranteed-valid capture combo. / Активная комбинация."""
        return normalize_hotkey(capture_hotkey) or DEFAULT_HOTKEY

    @staticmethod
    def _register(win32, combo: str, hotkey_id: int) -> bool:
        parsed = to_windows(combo)
        if parsed is None:
            return False
        mods, vk = parsed
        return bool(win32.RegisterHotKey(None, hotkey_id, mods, vk))

    def install(self, app, capture_hotkey: str = DEFAULT_HOTKEY) -> list[str]:
        """Register all hotkeys. Returns display names of the combos Windows refused.
        Регистрирует хоткеи; возвращает список занятых Windows комбинаций."""
        if not self.supported():
            return [capture_hotkey]
        import ctypes

        self._capture_combo = self.capture_hotkey(capture_hotkey)
        user32 = ctypes.windll.user32
        self._filter = _HotkeyEventFilter(self.actionRequested.emit)
        app.installNativeEventFilter(self._filter)
        failed: list[str] = []
        if not bool(user32.RegisterHotKey(None, FULLSCREEN_ID, MOD_CONTROL | MOD_SHIFT, VK_S)):
            failed.append("Ctrl+Shift+S")
        if not bool(user32.RegisterHotKey(None, REGION_ID, MOD_CONTROL | MOD_SHIFT, VK_R)):
            failed.append("Ctrl+Shift+R")
        if not self._register(user32, self._capture_combo, OVERLAY_ID):
            failed.append(self._capture_combo)
        if failed:
            logger.warning("global hotkey registration refused by Windows: %s", ", ".join(failed))
        else:
            logger.info("global hotkeys registered (capture: %s)", self._capture_combo)
        return failed

    def rebind_capture(self, combo: str) -> bool:
        """Re-register only the capture overlay hotkey, with rollback on failure.
        Перерегистрировать только снимок; при неудаче вернуть старую комбинацию."""
        combo = self.capture_hotkey(combo)
        if not self.supported() or self._filter is None:
            self._capture_combo = combo
            return True  # nothing to rebind off-Windows
        import ctypes

        user32 = ctypes.windll.user32
        old = self._capture_combo
        user32.UnregisterHotKey(None, OVERLAY_ID)
        if self._register(user32, combo, OVERLAY_ID):
            self._capture_combo = combo
            logger.info("capture hotkey rebound to %s", combo)
            return True
        logger.warning("capture hotkey rebind to %s refused by Windows — keeping %s", combo, old)
        # rollback to the previous combo — never leave the user without a hotkey
        self._register(user32, old, OVERLAY_ID)
        return False

    def shutdown(self) -> None:
        if not self.supported() or self._filter is None:
            return
        import ctypes

        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, FULLSCREEN_ID)
        user32.UnregisterHotKey(None, REGION_ID)
        user32.UnregisterHotKey(None, OVERLAY_ID)
        self._filter = None
