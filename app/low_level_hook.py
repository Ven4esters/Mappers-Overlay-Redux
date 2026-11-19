"""Low-level keyboard hook (WH_KEYBOARD_LL) — hotkeys that also work in games.
Низкоуровневый хук клавиатуры — хоткеи, работающие и поверх игр.

RegisterHotKey delivers via WM_HOTKEY to the registering thread's message
queue — exclusive fullscreen games that own input swallow it before it ever
arrives. WH_KEYBOARD_LL sees raw key events before delivery, which is how
ShareX & friends keep working in fullscreen. The hook never blocks normal
input — it only swallows the exact bound combos (same shadowing semantics
RegisterHotKey had).

RegisterHotKey доставляет клавишу через WM_HOTKEY в очередь потока —
exclusive-игры, владеющие вводом, перехватывают её раньше. WH_KEYBOARD_LL
видит сырые события до доставки — так ShareX и работает в полноэкранных
играх. Хук не мешает обычному вводу — «съедаются» только заданные комбинации.

Caveats / честно: не поможет против античита, висящего выше (FaceIT-like),
против процессов с более высокими правами (запускайте игру и приложение
одинаково) и против raw-input эксклюзива — там поможет borderless windowed.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("screensaver.hook")

WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
MOD_SHIFT, MOD_CONTROL, MOD_ALT, MOD_WIN = 0x0004, 0x0002, 0x0001, 0x0008
LLKHF_INJECTED = 0x00000010
HC_ACTION = 0
WH_KEYBOARD_LL = 13

# plain keys the capture overlay understands (no modifier needed) — routed
# here before combo matching so they work even while the fullscreen game
# holds the OS foreground window. / клавиши оверлея: ловим до совпадения комбо
_OVERLAY_KEYS = {
    0x1B: "escape",   # VK_ESCAPE
    0x0D: "enter",    # VK_RETURN (both Return/Enter)
    0x20: "enter",    # VK_SPACE confirms the highlighted mode
    0x31: "1", 0x32: "2", 0x33: "3",        # VK_1..VK_3
    0x61: "1", 0x62: "2", 0x63: "3",        # VK_NUMPAD1..VK_NUMPAD3
}


@dataclass(frozen=True)
class ComboBinding:
    """One hotkey combo bound to an action id. / Одна комбинация → действие."""

    mods: int
    vk: int
    action: str


def match_combo(bindings, mods: int, vk: int) -> str | None:
    """Exact modifier+key match; returns the action or None. / Точный матч."""
    for binding in bindings:
        if binding.mods == mods and binding.vk == vk:
            return binding.action
    return None


def force_foreground(hwnd: int) -> bool:
    """Best-effort OS foreground steal (Windows only). / Попытка честно дать окну
    foreground средствами Windows (только Windows).

    Qt's activateWindow() is silently denied for foreground-locked games
    (Windows foreground rules). The classic workaround — used by ShareX and
    friends — is AttachThreadInput to the current foreground thread, then
    SetForegroundWindow/BringWindowToTop, then detach. Games that keep OS
    foreground (raw input targets it) put the camera still and hand the mouse
    to the overlay. Returns True when our window ended up in the foreground.
    """
    if not sys.platform.startswith("win"):
        return False
    if not hwnd:
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.SetActiveWindow.argtypes = [wintypes.HWND]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    foreground = user32.GetForegroundWindow()
    our_thread = kernel32.GetCurrentThreadId()
    target_pid = wintypes.DWORD(0)
    foreground_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(target_pid)) if foreground else 0
    attached = False
    try:
        if foreground_thread and foreground_thread != our_thread:
            attached = bool(user32.AttachThreadInput(foreground_thread, our_thread, True))
        ok = bool(user32.SetForegroundWindow(wintypes.HWND(hwnd)))
        user32.BringWindowToTop(wintypes.HWND(hwnd))
        user32.SetActiveWindow(wintypes.HWND(hwnd))
        now_foreground = user32.GetForegroundWindow() == wintypes.HWND(hwnd)
        if ok and now_foreground:
            logger.info("foreground stolen for overlay (hwnd=%d)", int(hwnd))
            return True
        err = ctypes.get_last_error()
        logger.warning("foreground locked: SetForegroundWindow=%s, foreground after=%s "
                       "(hwnd=%d, GetLastError=%d) — the game keeps the mouse; use borderless",
                       ok, bool(now_foreground), int(hwnd), err)
        return False
    finally:
        if attached:
            user32.AttachThreadInput(foreground_thread, our_thread, False)


_mod_user32 = None


def current_mod_mask() -> int:
    """Current Ctrl/Shift/Alt/Win state via GetAsyncKeyState (Windows only).
    Текущие модификаторы — GetAsyncKeyState (только Windows).

    The DLL handle is cached — this runs for every key press.
    DLL кэшируется — функция вызывается на каждое нажатие.
    """
    global _mod_user32
    import ctypes

    if _mod_user32 is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        _mod_user32 = user32

    def down(vk: int) -> bool:
        return bool(_mod_user32.GetAsyncKeyState(vk) & 0x8000)

    mask = 0
    if down(0x11):  # VK_CONTROL
        mask |= MOD_CONTROL
    if down(0x10):  # VK_SHIFT
        mask |= MOD_SHIFT
    if down(0x12):  # VK_MENU (Alt)
        mask |= MOD_ALT
    if down(0x5B) or down(0x5C):  # VK_LWIN / VK_RWIN
        mask |= MOD_WIN
    return mask


class LowLevelKeyboardHook:
    """Installs WH_KEYBOARD_LL on the calling thread. / Ставит WH_KEYBOARD_LL.

    ``handle_key_event`` carries the event decision logic and is unit-testable
    on any platform; the ctypes plumbing is Windows-only.
    Логика — в ``handle_key_event`` (тестируется везде); ctypes — только Windows.
    """

    def __init__(self, handler: Callable[[str], None], bindings=()) -> None:
        self._handler = handler
        self._bindings = list(bindings)
        self._hook = None
        self._proc = None
        self._user32 = None
        self._struct = None
        self._overlay_active = False

    @staticmethod
    def supported() -> bool:
        return sys.platform.startswith("win")

    def set_bindings(self, bindings) -> None:
        self._bindings = list(bindings)

    def set_overlay_active(self, active: bool) -> None:
        """While True, capture Escape/Enter/1-3 for the overlay (swallow them).
        Пока True, Esc/Enter/1-3 «съедаются» для оверлея выбора режима."""
        self._overlay_active = bool(active)
        logger.info("overlay key pass-through %s", "enabled" if active else "disabled")

    @property
    def bindings(self) -> list[ComboBinding]:
        return list(self._bindings)

    @property
    def installed(self) -> bool:
        return self._hook is not None

    # ------------------------------------------------------------- events
    def handle_key_event(self, vk: int, mods: int, injected: bool = False) -> bool:
        """True → swallow the combo. / True — съесть комбинацию."""
        if injected:
            return False
        if self._overlay_active:
            overlay_key = _OVERLAY_KEYS.get(vk)
            if overlay_key is not None:
                logger.info("overlay key: %s", overlay_key)
                try:
                    self._handler(f"overlay:{overlay_key}")
                except Exception:  # noqa: BLE001 — a broken handler must not kill the hook
                    logger.exception("overlay command %r raised", overlay_key)
                return True
        action = match_combo(self._bindings, mods, vk)
        if action is None:
            return False
        logger.info("hotkey action: %s", action)
        try:
            self._handler(action)
        except Exception:  # noqa: BLE001 — a broken handler must not kill the hook
            logger.exception("hotkey action %r raised", action)
        return True

    # ------------------------------------------------------------- win32
    def install(self) -> bool:
        if not self.supported():
            return False
        import ctypes
        from ctypes import wintypes

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", wintypes.WPARAM)]

        # Explicit prototypes are mandatory on x64: ctypes defaults truncate
        # pointers (HINSTANCE, HHOOK) to 32-bit, which is why SetWindowsHookExW
        # used to fail silently. / Обязательные прототипы: без них ctypes режет
        # указатели до 32 бит на 64-битной Windows — хук «не ставился».
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                             ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        hook_proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                       wintypes.WPARAM, wintypes.LPARAM)(self._callback)
        hmod = kernel32.GetModuleHandleW(None)
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL,
                                        ctypes.cast(hook_proc, ctypes.c_void_p),
                                        hmod, 0)
        if not hook:
            err = ctypes.get_last_error()
            logger.error("SetWindowsHookExW(WH_KEYBOARD_LL) failed (error %d: %s)",
                         err, ctypes.WinError(err))
            return False
        self._hook = hook
        self._proc = hook_proc
        self._user32 = user32
        self._struct = KBDLLHOOKSTRUCT
        logger.info("low-level keyboard hook installed (%d bindings)", len(self._bindings))
        return True

    def uninstall(self) -> None:
        if self._hook is not None:
            try:
                self._user32.UnhookWindowsHookEx(self._hook)
                logger.info("low-level keyboard hook removed")
            except Exception:  # noqa: BLE001 — shutdown must not crash
                logger.exception("could not remove the keyboard hook")
        self._hook = None
        self._proc = None
        self._user32 = None
        self._struct = None

    def _callback(self, nCode, wParam, lParam):
        try:
            if nCode == HC_ACTION and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN) and self._struct:
                data = self._struct.from_address(lParam)
                if self.handle_key_event(int(data.vkCode), current_mod_mask(),
                                         bool(data.flags & LLKHF_INJECTED)):
                    return 1  # swallow — the game/app never sees the combo
        except Exception:  # noqa: BLE001 — never break the hook chain
            logger.exception("low-level hook callback error")
        if self._user32 is not None:
            return self._user32.CallNextHookEx(self._hook, nCode, wParam, lParam)
        return 0
