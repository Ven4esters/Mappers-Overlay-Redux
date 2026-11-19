"""Global hotkeys (Windows) — low-level hook first, RegisterHotKey as fallback.
Глобальные хоткеи (Windows): low-level hook, фоллбэк на RegisterHotKey.

Default bindings: capture overlay hotkey (configurable, default PrintScreen),
Ctrl+Shift+S (``fullscreen``), Ctrl+Shift+R (``region``).

On Windows we install a WH_KEYBOARD_LL hook (see ``app.low_level_hook``) so the
combos fire even when an exclusive fullscreen game owns keyboard input —
RegisterHotKey delivers via WM_HOTKEY and can be swallowed by those games.
If the hook cannot be installed, we fall back to RegisterHotKey (same public
behavior as before, but no guarantee inside fullscreen games).

На Windows ставим WH_KEYBOARD_LL — комбинации срабатывают даже поверх
полноэкранных игр; RegisterHotKey видел такие клавиши не всегда. Фоллбэк
на RegisterHotKey сохранён на случай запрета установки хука.

On non-Windows platforms ``supported()`` returns False and the manager is a
no-op; the in-window bindings for the same combos still work.
На не-Windows платформах менеджер неактивен; внутри окна работает всё.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, Signal

from app.hotkey_parse import DEFAULT_HOTKEY, normalize_hotkey, to_windows
from app.low_level_hook import ComboBinding, LowLevelKeyboardHook

logger = logging.getLogger("screensaver.hotkeys")

WM_HOTKEY = 0x0312
MOD_CONTROL, MOD_SHIFT = 0x0002, 0x0004
VK_S, VK_R = 0x53, 0x52
FULLSCREEN_ID, REGION_ID, OVERLAY_ID = 0xB10, 0xB11, 0xB12

BUILTIN_BINDINGS: tuple[tuple[str, str], ...] = (
    ("Ctrl+Shift+S", "fullscreen"),
    ("Ctrl+Shift+R", "region"),
)


def build_bindings(capture_hotkey: str) -> list[ComboBinding]:
    """Parse all three combos into hook bindings (skipping unparseable ones,
    logging the casualty). / Разобрать комбинации в привязки для хука."""
    bindings: list[ComboBinding] = []
    seen: set[tuple[int, int]] = set()
    for combo, action in (*BUILTIN_BINDINGS, (capture_hotkey, "overlay")):
        norm = normalize_hotkey(combo)
        parsed = to_windows(norm) if norm else None
        if parsed is None:
            logger.error("hotkey %r cannot be parsed — skipped", combo)
            continue
        mods, vk = parsed
        if (mods, vk) in seen:
            logger.warning("hotkey %r duplicates an earlier binding — first one wins", combo)
            continue
        seen.add((mods, vk))
        bindings.append(ComboBinding(mods, vk, action))
    return bindings


class HotkeyManager(QObject):
    """Registers/unregisters global hotkeys; emits ``actionRequested``.
    Регистрирует глобальные хоткеи; эмитит ``actionRequested(...)``."""

    actionRequested = Signal(str)  # "overlay" | "fullscreen" | "region"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hook: LowLevelKeyboardHook | None = None
        self._filter: object | None = None
        self._capture_combo: str = DEFAULT_HOTKEY

    @staticmethod
    def supported() -> bool:
        return sys.platform.startswith("win")

    @staticmethod
    def capture_hotkey(capture_hotkey: str) -> str:
        """Effective, guaranteed-valid capture combo. / Активная комбинация."""
        return normalize_hotkey(capture_hotkey) or DEFAULT_HOTKEY

    @property
    def hook_active(self) -> bool:
        return self._hook is not None and self._hook.installed

    # -------------------------------------------------------------- install
    def install(self, app, capture_hotkey: str = DEFAULT_HOTKEY) -> list[str]:
        """Register everything; returns combos Windows refused (empty on success).
        Регистрирует хоткеи; возвращает отвергнутые комбинации."""
        self._capture_combo = self.capture_hotkey(capture_hotkey)
        if not self.supported():
            return [self._capture_combo]

        bindings = build_bindings(self._capture_combo)
        hook = LowLevelKeyboardHook(self.actionRequested.emit, bindings)
        if hook.install():
            self._hook = hook
            logger.info("global hotkeys via low-level hook (capture: %s)", self._capture_combo)
            return []
        logger.warning("low-level hook unavailable — falling back to RegisterHotKey")

        import ctypes

        failed: list[str] = []
        user32 = ctypes.windll.user32
        # native event filter is needed only for the WM_HOTKEY fallback
        from app.hotkey_filter import HotkeyEventFilter

        self._filter = HotkeyEventFilter(self.actionRequested.emit)
        app.installNativeEventFilter(self._filter)
        if not bool(user32.RegisterHotKey(None, FULLSCREEN_ID, MOD_CONTROL | MOD_SHIFT, VK_S)):
            failed.append("Ctrl+Shift+S")
        if not bool(user32.RegisterHotKey(None, REGION_ID, MOD_CONTROL | MOD_SHIFT, VK_R)):
            failed.append("Ctrl+Shift+R")
        parsed = to_windows(self._capture_combo)
        if parsed is not None:
            mods, vk = parsed
            if not bool(user32.RegisterHotKey(None, OVERLAY_ID, mods, vk)):
                failed.append(self._capture_combo)
        else:
            failed.append(self._capture_combo)
        if failed:
            logger.warning("RegisterHotKey fallback refused: %s", ", ".join(failed))
        else:
            logger.info("global hotkeys via RegisterHotKey fallback (capture: %s)", self._capture_combo)
        return failed

    def rebind_capture(self, combo: str) -> bool:
        """Re-register only the capture overlay hotkey, rollback on failure.
        Перерегистрировать только снимок; при неудаче вернуть старую комбинацию."""
        combo = self.capture_hotkey(combo)
        if not self.supported():
            self._capture_combo = combo
            return True  # nothing to rebind off-Windows

        if self._hook is not None:
            self._capture_combo = combo
            self._hook.set_bindings(build_bindings(combo))
            logger.info("capture hotkey rebound to %s (hook)", combo)
            return True

        # fallback path: unregister old, register new, roll back on failure
        import ctypes

        user32 = ctypes.windll.user32
        old = self._capture_combo
        user32.UnregisterHotKey(None, OVERLAY_ID)
        parsed = to_windows(combo)
        if parsed is not None and bool(user32.RegisterHotKey(None, OVERLAY_ID, *parsed)):
            self._capture_combo = combo
            logger.info("capture hotkey rebound to %s (RegisterHotKey)", combo)
            return True
        old_parsed = to_windows(old)
        if old_parsed is not None:
            user32.RegisterHotKey(None, OVERLAY_ID, *old_parsed)
        logger.warning("capture hotkey rebind to %s refused — keeping %s", combo, old)
        return False

    def shutdown(self) -> None:
        if self._hook is not None:
            self._hook.uninstall()
            self._hook = None
            return
        if not self.supported() or self._filter is None:
            return
        import ctypes

        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(None, FULLSCREEN_ID)
        user32.UnregisterHotKey(None, REGION_ID)
        user32.UnregisterHotKey(None, OVERLAY_ID)
        self._filter = None
