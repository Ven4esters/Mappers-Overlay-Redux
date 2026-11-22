"""Отправка клавиш и кликов мышью через Windows ``SendInput``.

Модуль импортируется на любой платформе; работать может только на Windows —
иначе :meth:`Win32InputBackend.is_ready` вернёт ``False``, а вызовы поднимут
:class:`InputUnavailableError`.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from typing import Any, Final, Protocol

LOGGER = logging.getLogger(__name__)

INPUT_MOUSE: Final = 0
INPUT_KEYBOARD: Final = 1
KEYEVENTF_KEYUP: Final = 0x0002
MOUSEEVENTF_MOVE: Final = 0x0001
MOUSEEVENTF_ABSOLUTE: Final = 0x8000
MOUSEEVENTF_LEFTDOWN: Final = 0x0002
MOUSEEVENTF_LEFTUP: Final = 0x0004
SM_CXSCREEN: Final = 0
SM_CYSCREEN: Final = 1
PROCESS_PER_MONITOR_DPI_AWARE: Final = 2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: Final = -4

VK_CODES: Final[dict[str, int]] = {
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "enter": 0x0D,
    "esc": 0x1B,
    "space": 0x20,
    **{letter: ord(letter.upper()) for letter in "abcdefghijklmnopqrstuvwxyz"},
    **{digit: ord(digit) for digit in "0123456789"},
}


class InputUnavailableError(RuntimeError):
    """Ввод недоступен: не Windows или вызов Win32 не удался."""


@dataclass(frozen=True, slots=True)
class ForegroundState:
    """Куда придётся клик, если нажать прямо сейчас."""

    target_window: int
    foreground_window: int
    needs_activation: bool


class InputBackend(Protocol):
    """Контракт устройства ввода."""

    def is_ready(self) -> bool:
        """Есть ли возможность отправлять ввод."""

    def ensure_foreground(self, x: int, y: int) -> bool:
        """Активирует окно под точкой, если оно не в фокусе. True — кликали."""

    def press_combination(self, *keys: str) -> None:
        """Нажимает клавиши одновременно (например, ``ctrl`` + ``a``)."""

    def tap_key(self, key: str) -> None:
        """Нажимает и отпускает одну клавишу."""

    def click(self, x: int, y: int) -> None:
        """Кликает левой кнопкой по экранной точке."""


if sys.platform == "win32":  # pragma: no cover - выполняется только на Windows
    _ULONG_PTR = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_uint32),
            ("dwFlags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_uint16),
            ("wScan", ctypes.c_uint16),
            ("dwFlags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("union", _INPUTUNION)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.WindowFromPoint.argtypes = (ctypes.c_long, ctypes.c_long)
    _user32.WindowFromPoint.restype = ctypes.c_void_p
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _user32.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    _user32.GetAncestor.restype = ctypes.c_void_p
    _user32.SendInput.argtypes = (ctypes.c_uint32, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = ctypes.c_uint32
    _user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    _user32.GetSystemMetrics.restype = ctypes.c_int


else:  # pragma: no cover - только для проверки типов и импорта на Linux
    _user32: Any = None
    _INPUT: Any = None
    _MOUSEINPUT: Any = None
    _KEYBDINPUT: Any = None


def enable_dpi_awareness() -> bool:
    """Включает Per-Monitor V2 DPI awareness до создания QApplication.

    Без этого Windows отдаёт координаты курсора в «логических» пикселях, а
    ``SendInput`` ждёт физические: при масштабе 125–150 % клик уходит мимо поля,
    и координаты «меняются в программе, но не в игре».
    """
    if sys.platform != "win32":  # pragma: no cover - проверяется на Linux
        return False
    try:  # pragma: no cover - Windows
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = (ctypes.c_void_p,)
        set_context.restype = ctypes.c_bool
        if set_context(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
            return True
    except (AttributeError, OSError):
        LOGGER.debug("SetProcessDpiAwarenessContext недоступен")
    try:  # pragma: no cover - Windows 8.1+
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        set_awareness = shcore.SetProcessDpiAwareness
        set_awareness.argtypes = (ctypes.c_int,)
        if set_awareness(PROCESS_PER_MONITOR_DPI_AWARE) == 0:
            return True
    except (AttributeError, OSError):
        LOGGER.debug("SetProcessDpiAwareness недоступен")
    return False


def window_at_point(x: int, y: int) -> int:
    """HWND окна под точкой (0, если окна нет)."""
    if sys.platform != "win32":  # pragma: no cover
        return 0
    return int(_user32.WindowFromPoint(x, y) or 0)


def _root_window(hwnd: int) -> int:
    """Верхнеуровневое окно для дочернего HWND."""
    if sys.platform != "win32" or not hwnd:  # pragma: no cover
        return 0
    return int(_user32.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT = 2


def foreground_window() -> int:
    """HWND активного окна."""
    if sys.platform != "win32":  # pragma: no cover
        return 0
    return int(_user32.GetForegroundWindow() or 0)


def foreground_state(x: int, y: int) -> ForegroundState:
    """Сравнивает окно под точкой с активным окном."""
    target = _root_window(window_at_point(x, y))
    active = foreground_window()
    return ForegroundState(
        target_window=target,
        foreground_window=active,
        needs_activation=bool(target) and target != active,
    )


class Win32InputBackend:
    """Реализация :class:`InputBackend` поверх ``SendInput``."""

    def is_ready(self) -> bool:
        """Готов ли бэкенд (только Windows)."""
        return sys.platform == "win32"

    def press_combination(self, *keys: str) -> None:
        """Нажимает модификаторы, затем клавишу, и отпускает всё в обратном порядке."""
        if not keys:
            raise ValueError("нужна хотя бы одна клавиша")
        virtual_keys = [self._virtual_key(key) for key in keys]
        for code in virtual_keys:
            self._send_key(code, key_up=False)
        for code in reversed(virtual_keys):
            self._send_key(code, key_up=True)

    def ensure_foreground(self, x: int, y: int) -> bool:
        """Кликает по точке, если окно игры не активно (иначе первый клик съедается)."""
        state = foreground_state(x, y)
        if not state.needs_activation:
            return False
        LOGGER.debug("Активирую окно %s кликом по %s,%s", state.target_window, x, y)
        self.click(x, y)
        return True

    def tap_key(self, key: str) -> None:
        """Одиночное нажатие клавиши."""
        code = self._virtual_key(key)
        self._send_key(code, key_up=False)
        self._send_key(code, key_up=True)

    def click(self, x: int, y: int) -> None:
        """Клик левой кнопкой по абсолютным координатам экрана."""
        self._require_windows()
        width = _user32.GetSystemMetrics(SM_CXSCREEN)
        height = _user32.GetSystemMetrics(SM_CYSCREEN)
        if width <= 0 or height <= 0:  # pragma: no cover - защита от странного окружения
            raise InputUnavailableError("не удалось определить размер экрана")
        normalised_x = int(x * 65535 / (width - 1))
        normalised_y = int(y * 65535 / (height - 1))
        self._send_inputs(
            [
                self._mouse_input(
                    normalised_x, normalised_y, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                ),
                self._mouse_input(
                    normalised_x, normalised_y, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE
                ),
                self._mouse_input(
                    normalised_x, normalised_y, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE
                ),
            ]
        )

    @staticmethod
    def _virtual_key(key: str) -> int:
        code = VK_CODES.get(key.lower())
        if code is None:
            raise InputUnavailableError(f"неизвестная клавиша: {key}")
        return code

    @staticmethod
    def _require_windows() -> None:
        if sys.platform != "win32":  # pragma: no cover - проверяется на Linux
            raise InputUnavailableError("ввод через SendInput доступен только в Windows")

    def _send_key(self, virtual_key: int, *, key_up: bool) -> None:
        self._require_windows()
        self._send_inputs([self._key_input(virtual_key, key_up=key_up)])

    @staticmethod
    def _key_input(virtual_key: int, *, key_up: bool) -> _INPUT:  # pragma: no cover - Windows
        event = _INPUT(type=INPUT_KEYBOARD)
        event.union.ki = _KEYBDINPUT(
            wVk=virtual_key,
            wScan=0,
            dwFlags=KEYEVENTF_KEYUP if key_up else 0,
            time=0,
            dwExtraInfo=0,
        )
        return event

    @staticmethod
    def _mouse_input(x: int, y: int, flags: int) -> _INPUT:  # pragma: no cover - Windows
        event = _INPUT(type=INPUT_MOUSE)
        event.union.mi = _MOUSEINPUT(dx=x, dy=y, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)
        return event

    @staticmethod
    def _send_inputs(events: list[_INPUT]) -> None:  # pragma: no cover - Windows
        count = len(events)
        array = (_INPUT * count)(*events)
        sent = _user32.SendInput(count, array, ctypes.sizeof(_INPUT))
        if sent != count:
            error = getattr(ctypes, "get_last_error", lambda: 0)()
            LOGGER.error("SendInput отправил %s из %s событий (ошибка %s)", sent, count, error)
            raise InputUnavailableError(f"SendInput не сработал, код ошибки {error}")


class NullInputBackend:
    """Заглушка для тестов и не-Windows окружений."""

    def is_ready(self) -> bool:
        """Всегда ``False`` — ввод недоступен."""
        return False

    def ensure_foreground(self, x: int, y: int) -> bool:
        """Ничего не делает."""
        raise InputUnavailableError("ввод недоступен")

    def press_combination(self, *keys: str) -> None:
        """Ничего не делает."""
        raise InputUnavailableError("ввод недоступен")

    def tap_key(self, key: str) -> None:
        """Ничего не делает."""
        raise InputUnavailableError("ввод недоступен")

    def click(self, x: int, y: int) -> None:
        """Ничего не делает."""
        raise InputUnavailableError("ввод недоступен")
