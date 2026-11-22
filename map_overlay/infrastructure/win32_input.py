"""Win32: клики, клавиатурные сочетания и позиция курсора через ``SendInput``."""

from __future__ import annotations

import ctypes
import sys
from typing import ClassVar, Final

from map_overlay.domain.point import Point
from map_overlay.errors import InputError, UnsupportedPlatformError

VK_CONTROL: Final = 0x11
VK_A: Final = 0x41
VK_C: Final = 0x43
VK_V: Final = 0x56

INPUT_MOUSE: Final = 0
INPUT_KEYBOARD: Final = 1
KEYEVENTF_KEYUP: Final = 0x0002
MOUSEEVENTF_LEFTDOWN: Final = 0x0002
MOUSEEVENTF_LEFTUP: Final = 0x0004

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: Final = -4
SM_CXSCREEN: Final = 0
SM_CYSCREEN: Final = 1

_Fields = list[tuple[str, object]]
"""Описание полей ctypes-структуры."""


class _MouseInput(ctypes.Structure):
    _fields_: ClassVar[_Fields] = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouse_data", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("extra_info", ctypes.c_void_p),
    ]


class _KeybdInput(ctypes.Structure):
    _fields_: ClassVar[_Fields] = [
        ("vk", ctypes.c_ushort),
        ("scan", ctypes.c_ushort),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("extra_info", ctypes.c_void_p),
    ]


class _InputUnion(ctypes.Union):
    _fields_: ClassVar[_Fields] = [
        ("mouse", _MouseInput),
        ("keyboard", _KeybdInput),
    ]


class _Input(ctypes.Structure):
    _fields_: ClassVar[_Fields] = [("type", ctypes.c_ulong), ("data", _InputUnion)]


class _NativePoint(ctypes.Structure):
    _fields_: ClassVar[_Fields] = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def enable_dpi_awareness() -> bool:
    """Включить Per-Monitor V2, чтобы клики шли в физических пикселях.

    Returns:
        ``True``, если режим включён (или уже был включён системой).
    """
    if sys.platform != "win32":
        return False
    windll = ctypes.windll
    try:
        if windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        ):
            return True
    except (AttributeError, OSError):
        pass
    try:
        return bool(windll.user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


class WindowsInput:
    """Реализация :class:`map_overlay.application.ports.InputPort` для Windows."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Клики и клавиши доступны только в Windows")
        windll = ctypes.windll
        self._user32 = windll.user32
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(_NativePoint)]
        self._user32.SendInput.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(_Input),
            ctypes.c_int,
        ]

    def click(self, point: Point) -> None:
        """Навести курсор в точку и кликнуть."""
        self.move_cursor(point)
        self._send_mouse(MOUSEEVENTF_LEFTDOWN)
        self._send_mouse(MOUSEEVENTF_LEFTUP)

    def select_all(self) -> None:
        """Нажать ``Ctrl+A``."""
        self._send_combo(VK_A)

    def copy(self) -> None:
        """Нажать ``Ctrl+C``."""
        self._send_combo(VK_C)

    def paste(self) -> None:
        """Нажать ``Ctrl+V``."""
        self._send_combo(VK_V)

    def cursor_position(self) -> Point:
        """Текущая позиция курсора в физических пикселях."""
        native = _NativePoint()
        if not self._user32.GetCursorPos(ctypes.byref(native)):
            raise InputError("Не удалось получить позицию курсора")
        return Point(x=int(native.x), y=int(native.y))

    def move_cursor(self, point: Point) -> None:
        """Переместить курсор без клика."""
        if not self._user32.SetCursorPos(int(point.x), int(point.y)):
            raise InputError(f"Не удалось перевести курсор в точку {point}")

    def screen_size(self) -> Point:
        """Размер основного экрана в пикселях."""
        return Point(
            x=int(self._user32.GetSystemMetrics(SM_CXSCREEN)),
            y=int(self._user32.GetSystemMetrics(SM_CYSCREEN)),
        )

    def _send_combo(self, key: int) -> None:
        self._send_keys(((VK_CONTROL, True), (key, True), (key, False), (VK_CONTROL, False)))

    def _send_keys(self, events: tuple[tuple[int, bool], ...]) -> None:
        payload = (_Input * len(events))()
        for index, (vk, is_down) in enumerate(events):
            payload[index].type = INPUT_KEYBOARD
            payload[index].data.keyboard.vk = vk
            payload[index].data.keyboard.flags = 0 if is_down else KEYEVENTF_KEYUP
        self._send(payload, len(events))

    def _send_mouse(self, flags: int) -> None:
        payload = (_Input * 1)()
        payload[0].type = INPUT_MOUSE
        payload[0].data.mouse.flags = flags
        self._send(payload, 1)

    def _send(self, payload: ctypes.Array[_Input], count: int) -> None:
        sent = self._user32.SendInput(count, payload, ctypes.sizeof(_Input))
        if sent != count:
            raise InputError("Windows не принял ввод: SendInput вернул ошибку")
