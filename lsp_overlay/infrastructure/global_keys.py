"""Глобальные клавиши: хук, который забирает Numpad у игры, пока идёт живой режим.

Почему хук, а не опрос. ``GetAsyncKeyState`` показывает нажатие, но не отбирает его:
клиент видит те же клавиши и вертит камеру, а объект в редакторе уезжает сам.
Низкоуровневый хук ``WH_KEYBOARD_LL`` позволяет вернуть ``1`` и погасить клавишу —
игра её уже не получит, а нам приходят и нажатие, и отпускание.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

LOGGER = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
SWALLOW_KEY = 1
PASS_KEY = 0
NUMPAD_FIRST_VK = 0x60
NUMPAD_LAST_VK = 0x6F

KeyCallback = Callable[[int, bool], None]


class _KeyboardHookStruct(ctypes.Structure):
    _fields_ = (
        ("vk_code", wintypes.DWORD),
        ("scan_code", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", ctypes.c_void_p),
    )


class GlobalKeyHookPort:
    """Контракт глобального перехвата клавиш (порт для прикладного слоя)."""

    def is_available(self) -> bool:
        """Есть ли возможность перехватывать клавиши вне окна оверлея."""
        raise NotImplementedError

    def start(self, callback: KeyCallback) -> bool:
        """Ставит хук; ``callback(vk_code, pressed)`` зовётся для клавиш Numpad."""
        raise NotImplementedError

    def stop(self) -> None:
        """Снимает хук."""
        raise NotImplementedError


class Win32KeyHook(GlobalKeyHookPort):
    """Хук клавиатуры Windows: гасит Numpad и отдаёт события в оверлей."""

    def __init__(self) -> None:
        self._user32: Any = _load_user32()
        self._hook: int | None = None
        self._callback: KeyCallback | None = None
        self._proc: Any = None

    def is_available(self) -> bool:
        """Хук доступен только на Windows."""
        return self._user32 is not None

    def start(self, callback: KeyCallback) -> bool:
        """Ставит хук клавиатуры. Возвращает ``True``, если он встал."""
        if self._user32 is None or self._hook is not None:
            return False
        self._callback = callback
        handle = self._user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._handler(), None, 0)
        if not handle:
            LOGGER.warning("Не удалось поставить хук клавиатуры, код %s", _last_error())
            self._callback = None
            return False
        self._hook = handle
        LOGGER.info("Хук клавиатуры включён: Numpad забирается у игры")
        return True

    def stop(self) -> None:
        """Снимает хук, если он стоял."""
        if self._user32 is None or self._hook is None:
            return
        self._user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        self._callback = None
        LOGGER.info("Хук клавиатуры снят: клавиши снова видит игра")

    def _handler(self) -> Any:
        """Создаёт и запоминает C-функцию обратного вызова (без неё хук не живёт)."""
        pointer = ctypes.POINTER(_KeyboardHookStruct)  # noqa: UP007 - тип ctypes
        prototype = _winfunctype()(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, pointer)

        def callback(code: int, message: int, data: Any) -> int:
            if code < 0 or data is None:
                return _call_next(self._user32, self._hook, code, message, data)
            vk_code = int(data.contents.vk_code)
            if not NUMPAD_FIRST_VK <= vk_code <= NUMPAD_LAST_VK:
                return _call_next(self._user32, self._hook, code, message, data)
            pressed = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
            released = message in (WM_KEYUP, WM_SYSKEYUP)
            if (pressed or released) and self._callback is not None:
                try:
                    self._callback(vk_code, pressed)
                except Exception:  # noqa: BLE001 - из C-колбэка нельзя выпускать исключение
                    LOGGER.exception("Ошибка обработчика глобальной клавиши")
            return SWALLOW_KEY

        self._proc = prototype(callback)
        return self._proc


class NullKeyHook(GlobalKeyHookPort):
    """Заглушка: хука нет, клавиши читаются только в окне оверлея."""

    def is_available(self) -> bool:
        """Всегда ``False``."""
        return False

    def start(self, callback: KeyCallback) -> bool:  # noqa: ARG002 - заглушка
        """Ничего не перехватывает."""
        return False

    def stop(self) -> None:
        """Ничего не делает."""


def _winfunctype() -> Any:
    """``WINFUNCTYPE`` есть только в Windows-сборке ctypes."""
    return getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


def _last_error() -> int:
    """Код последней ошибки Win32 (вне Windows — ноль)."""
    return int(getattr(ctypes, "get_last_error", lambda: 0)())


def _load_user32() -> Any:
    """Возвращает ``user32.dll`` с нужными сигнатурами или ``None`` вне Windows."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = (
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
    return user32


def _call_next(user32: Any, hook: int | None, code: int, message: int, data: object) -> int:
    """Передаёт событие следующему хуку (``CallNextHookEx``)."""
    if user32 is None:
        return PASS_KEY
    return int(user32.CallNextHookEx(hook, code, message, data))
