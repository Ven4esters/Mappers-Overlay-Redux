from __future__ import annotations

import ctypes
import sys
import time

import pyperclip

from ..logger import get_logger
from .base import AutomationError, InputBackend


logger = get_logger("mapper_assist.automation.win32")

ULONG_PTR = ctypes.c_size_t


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class WIN32_INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("union", _INPUT_UNION),
    ]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002

VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LMENU = 0xA4
VK_RMENU = 0xA5

GA_ROOT = 2


class Win32InputBackend(InputBackend):
    """Нативный драйвер ввода для Windows 10/11 (FiveM Borderless Windowed / NUI CEF)."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32InputBackend поддерживается только на Windows")
        from ctypes import wintypes

        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(WIN32_INPUT), ctypes.c_int]
        self._user32.SendInput.restype = ctypes.c_uint
        self._user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self._user32.MapVirtualKeyW.restype = ctypes.c_uint
        self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.WindowFromPoint.argtypes = [_POINT]
        self._user32.WindowFromPoint.restype = wintypes.HWND
        self._user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        self._user32.GetAncestor.restype = wintypes.HWND
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._kernel32.GetLastError.argtypes = []
        self._kernel32.GetLastError.restype = wintypes.DWORD

        logger.debug("Win32InputBackend инициализирован (sizeof(INPUT)=%d)", ctypes.sizeof(WIN32_INPUT))

    def get_cursor_pos(self) -> tuple[int, int]:
        pt = _POINT()
        if not self._user32.GetCursorPos(ctypes.byref(pt)):
            err = self._kernel32.GetLastError()
            logger.warning("GetCursorPos вернул False (GetLastError=%d)", err)
        return int(pt.x), int(pt.y)

    def set_cursor_pos(self, x: int, y: int) -> None:
        if not self._user32.SetCursorPos(int(x), int(y)):
            err = self._kernel32.GetLastError()
            logger.warning("SetCursorPos(%d, %d) вернул False (GetLastError=%d)", x, y, err)

    def _send_inputs(self, items: list[WIN32_INPUT]) -> None:
        arr = (WIN32_INPUT * len(items))(*items)
        sent = int(self._user32.SendInput(len(items), arr, ctypes.sizeof(WIN32_INPUT)))
        if sent != len(items):
            err = self._kernel32.GetLastError()
            logger.error(
                "SendInput отправил %d из %d событий (GetLastError=%d). "
                "Возможна блокировка UIPI (FiveM запущен от Администратора, а программа — нет).",
                sent,
                len(items),
                err,
            )

    def _key_event(self, vk: int, key_up: bool = False) -> WIN32_INPUT:
        scan = int(self._user32.MapVirtualKeyW(vk, 0))
        flags = KEYEVENTF_KEYUP if key_up else 0
        inp = WIN32_INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki = _KEYBDINPUT(
            wVk=vk,
            wScan=scan,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        )
        return inp

    def _mouse_button_event(self, flags: int) -> WIN32_INPUT:
        inp = WIN32_INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi = _MOUSEINPUT(
            dx=0,
            dy=0,
            mouseData=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        )
        return inp

    def left_click(self, x: int, y: int) -> None:
        self.set_cursor_pos(x, y)
        time.sleep(0.008)
        self._send_inputs([self._mouse_button_event(MOUSEEVENTF_LEFTDOWN)])
        time.sleep(0.012)
        self._send_inputs([self._mouse_button_event(MOUSEEVENTF_LEFTUP)])

    def wait_modifiers_released(self, timeout_ms: int = 320) -> None:
        """Ждёт отпускания Alt/Shift перед отправкой Ctrl+A/V или Enter (защита от Alt+Enter в GTA V)."""
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            alt_down = bool(self._user32.GetAsyncKeyState(VK_MENU) & 0x8000)
            shift_down = bool(self._user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
            if not alt_down and not shift_down:
                return
            time.sleep(0.010)

        logger.debug("Модификаторы Alt/Shift всё ещё зажаты спустя %d мс — выполняем программный сброс", timeout_ms)
        self._send_inputs(
            [
                self._key_event(VK_LMENU, key_up=True),
                self._key_event(VK_RMENU, key_up=True),
                self._key_event(VK_MENU, key_up=True),
                self._key_event(VK_SHIFT, key_up=True),
            ]
        )
        time.sleep(0.010)

    def send_ctrl_Combo(self, letter: str) -> None:
        vk = ord(letter.upper()[0])
        self._send_inputs([self._key_event(VK_CONTROL, key_up=False)])
        time.sleep(0.006)
        self._send_inputs([self._key_event(vk, key_up=False)])
        time.sleep(0.010)
        self._send_inputs(
            [
                self._key_event(vk, key_up=True),
                self._key_event(VK_CONTROL, key_up=True),
            ]
        )

    def send_enter(self) -> None:
        self._send_inputs([self._key_event(VK_RETURN, key_up=False)])
        time.sleep(0.012)
        self._send_inputs([self._key_event(VK_RETURN, key_up=True)])

    def ensure_window_at_point_focused(
        self,
        x: int,
        y: int,
        neutral_point: tuple[int, int] | None,
        settle_ms: int,
    ) -> None:
        pt = _POINT(int(x), int(y))
        hwnd_at_pt = self._user32.WindowFromPoint(pt)
        if not hwnd_at_pt:
            logger.warning("WindowFromPoint(%d, %d) не нашёл окно под курсором", x, y)
            return
        target_root = self._user32.GetAncestor(hwnd_at_pt, GA_ROOT) or hwnd_at_pt
        fg_hwnd = self._user32.GetForegroundWindow()
        if fg_hwnd and target_root and fg_hwnd != target_root:
            wake_x, wake_y = neutral_point if neutral_point is not None else (x, y)
            logger.debug(
                "Передача фокуса целевому окну (fg=%s -> target=%s) через клик (%d, %d)",
                hex(fg_hwnd),
                hex(target_root),
                wake_x,
                wake_y,
            )
            self.left_click(wake_x, wake_y)
            time.sleep(max(0.02, settle_ms / 1000.0))

    def get_clipboard(self) -> str:
        last_err: Exception | None = None
        for attempt in range(6):
            try:
                return pyperclip.paste() or ""
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.debug("Повтор чтения буфера обмена #%d из-за ошибки: %s", attempt + 1, exc)
                time.sleep(0.008)
        logger.error("Критическая ошибка чтения буфера обмена после 6 попыток: %s", last_err)
        raise AutomationError(f"Не удалось прочитать буфер обмена: {last_err}")

    def set_clipboard(self, text: str) -> None:
        last_err: Exception | None = None
        for attempt in range(6):
            try:
                pyperclip.copy(text)
                return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.debug("Повтор записи буфера обмена #%d из-за ошибки: %s", attempt + 1, exc)
                time.sleep(0.008)
        logger.error("Критическая ошибка записи в буфер обмена после 6 попыток: %s", last_err)
        raise AutomationError(f"Не удалось записать в буфер обмена: {last_err}")
