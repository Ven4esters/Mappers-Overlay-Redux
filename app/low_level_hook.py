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

    @staticmethod
    def supported() -> bool:
        return sys.platform.startswith("win")

    def set_bindings(self, bindings) -> None:
        self._bindings = list(bindings)

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
