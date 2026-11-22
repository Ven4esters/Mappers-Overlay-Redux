"""Глобальные горячие клавиши через низкоуровневый хук клавиатуры Windows.

Клавиши забираются у игры: нажатие на Numpad не крутит камеру и не открывает меню.
Хук живёт в отдельном потоке с собственным циклом сообщений — так Windows не рвёт
его по таймауту, а интерфейс не подвисает.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable, Collection
from typing import ClassVar, Final

from PySide6.QtCore import QObject, QThread, Signal

from map_overlay.domain.keynames import VK_NUMLOCK

logger = logging.getLogger(__name__)

WH_KEYBOARD_LL: Final = 13
WM_KEYDOWN: Final = 0x0100
WM_KEYUP: Final = 0x0101
WM_SYSKEYDOWN: Final = 0x0104
WM_SYSKEYUP: Final = 0x0105
WM_QUIT: Final = 0x0012
HOOK_TIMEOUT_MS: Final = 2000

_Fields = list[tuple[str, object]]


class _KeyboardHookData(ctypes.Structure):
    _fields_: ClassVar[_Fields] = [
        ("vk", ctypes.c_ulong),
        ("scan", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("extra", ctypes.c_void_p),
    ]


class _Message(ctypes.Structure):
    _fields_: ClassVar[_Fields] = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wparam", ctypes.c_size_t),
        ("lparam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
        ("private", ctypes.c_ulong),
    ]


_HOOK_PROC = ctypes.CFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


class WindowsHotkeySource(QThread):
    """Поток с хуком клавиатуры.

    ``key_event`` испускается из потока хука; подписчик получает событие в своём
    потоке (Qt ставит его в очередь), поэтому интерфейс обновляется безопасно.
    """

    key_event = Signal(int, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bound: frozenset[int] = frozenset()
        self._learning = False
        self._callback: Callable[[int, bool], None] | None = None
        self._thread_id = 0
        self._hook: int | None = None
        self._proc: object | None = None
        self.failed = False

    def start_listening(self, on_key: Callable[[int, bool], None]) -> None:
        """Запустить хук и доставлять нажатия в ``on_key``."""
        self._callback = on_key
        self.key_event.connect(self._deliver)
        if sys.platform != "win32":
            self.failed = True
            logger.error("Горячие клавиши доступны только в Windows")
            return
        super().start()

    def stop_listening(self) -> None:
        """Остановить хук и дождаться потока."""
        if sys.platform == "win32" and self._thread_id:
            windll = ctypes.windll
            windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self.isRunning():
            self.wait(HOOK_TIMEOUT_MS)

    def configure(self, *, bound_keys: Collection[int], learning: bool) -> None:
        """Сказать хуку, какие клавиши перехватывать."""
        self._bound = frozenset(bound_keys)
        self._learning = learning

    def num_lock_enabled(self) -> bool | None:
        """Включён ли NumLock."""
        if sys.platform != "win32":
            return None
        return bool(ctypes.windll.user32.GetKeyState(VK_NUMLOCK) & 1)

    def is_available(self) -> bool:
        """Установлен ли хук."""
        return not self.failed and sys.platform == "win32"

    def run(self) -> None:
        """Установить хук и крутить цикл сообщений потока."""
        windll = ctypes.windll
        user32 = windll.user32
        kernel32 = windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        self._proc = _HOOK_PROC(self._handle)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not self._hook:
            self.failed = True
            logger.error("Не удалось установить хук клавиатуры")
            return
        logger.info("Хук клавиатуры установлен")
        message = _Message()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        logger.info("Хук клавиатуры снят")

    def _deliver(self, vk: int, is_down: bool) -> None:
        if self._callback is not None:
            self._callback(vk, is_down)

    def _handle(self, code: int, wparam: int, lparam: int) -> int:
        user32 = ctypes.windll.user32
        if code < 0:
            return int(user32.CallNextHookEx(None, code, wparam, lparam))
        data = ctypes.cast(lparam, ctypes.POINTER(_KeyboardHookData)).contents
        vk = int(data.vk)
        is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = wparam in (WM_KEYUP, WM_SYSKEYUP)
        if (is_down or is_up) and (self._learning or vk in self._bound):
            self.key_event.emit(vk, is_down)
            return 1
        return int(user32.CallNextHookEx(None, code, wparam, lparam))
