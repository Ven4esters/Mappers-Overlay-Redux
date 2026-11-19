from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import threading
from typing import Callable

from .logger import get_logger


logger = get_logger("mapper_assist.hotkeys")


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_MAP: dict[str, int] = {
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PGUP": 0x21,
    "PAGEDOWN": 0x22,
    "PGDN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "NUMPAD0": 0x60,
    "NUMPAD1": 0x61,
    "NUMPAD2": 0x62,
    "NUMPAD3": 0x63,
    "NUMPAD4": 0x64,
    "NUMPAD5": 0x65,
    "NUMPAD6": 0x66,
    "NUMPAD7": 0x67,
    "NUMPAD8": 0x68,
    "NUMPAD9": 0x69,
    "NUM0": 0x60,
    "NUM1": 0x61,
    "NUM2": 0x62,
    "NUM3": 0x63,
    "NUM4": 0x64,
    "NUM5": 0x65,
    "NUM6": 0x66,
    "NUM7": 0x67,
    "NUM8": 0x68,
    "NUM9": 0x69,
    "ADD": 0x6B,
    "PLUS": 0xBB,
    "SUBTRACT": 0x6D,
    "MINUS": 0xBD,
}

for _i in range(1, 25):
    VK_MAP[f"F{_i}"] = 0x70 + (_i - 1)


def parse_hotkey_spec(spec: str) -> tuple[int, int] | None:
    """
    Разбирает строку вида 'Alt+Right', 'Ctrl+Shift+F5', 'F8', 'Numpad6'
    в кортеж (win32_modifiers, virtual_key_code).
    Возвращает None, если строка пустая или некорректная.
    """
    if not spec or not spec.strip():
        return None

    parts = [p.strip().upper() for p in spec.split("+") if p.strip()]
    if not parts:
        return None

    mods = MOD_NOREPEAT
    vk: int | None = None

    for token in parts:
        if token in ("ALT", "LALT", "RALT"):
            mods |= MOD_ALT
        elif token in ("CTRL", "CONTROL", "LCTRL", "RCTRL"):
            mods |= MOD_CONTROL
        elif token in ("SHIFT", "LSHIFT", "RSHIFT"):
            mods |= MOD_SHIFT
        elif token in ("WIN", "META", "SUPER"):
            mods |= MOD_WIN
        elif token in VK_MAP:
            vk = VK_MAP[token]
        elif len(token) == 1 and token.isalnum():
            vk = ord(token)
        else:
            return None

    if vk is None:
        return None
    return mods, vk


class GlobalHotkeyService:
    """
    Нативный менеджер глобальных горячих клавиш на базе Win32 RegisterHotKey.
    Преимущества для FiveM:
      - Не ставит низкоуровневых хуков клавиатуры (0% нагрузки на CPU, полная совместимость с античитом);
      - Перехватывает хоткей на уровне ОС, чтобы нажатия Alt+Стрелки / F5 не управляли персонажем в игре.
    """

    def __init__(self, on_action: Callable[[str], None]) -> None:
        self._on_action = on_action
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready_event = threading.Event()
        self._lock = threading.Lock()
        self._active_bindings: dict[str, str] = {}
        self._failed_bindings: list[str] = []

    @property
    def is_supported(self) -> bool:
        return sys.platform == "win32"

    @property
    def failed_bindings(self) -> list[str]:
        return list(self._failed_bindings)

    def start(self, bindings: dict[str, str]) -> list[str]:
        """Запускает или перезапускает регистрацию словаря {action_id: hotkey_str}."""
        self.stop()
        self._active_bindings = dict(bindings)
        self._failed_bindings = []

        if not self.is_supported or not bindings:
            return []

        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self._win32_loop,
            args=(dict(bindings),),
            name="LSPMapperHotkeyThread",
            daemon=True,
        )
        self._thread.start()
        self._ready_event.wait(timeout=1.5)
        return list(self._failed_bindings)

    def stop(self) -> None:
        with self._lock:
            tid = self._thread_id
            thread = self._thread
            self._thread_id = None
            self._thread = None

        if self.is_supported and tid is not None:
            user32 = ctypes.windll.user32
            user32.PostThreadMessageW.argtypes = [
                wintypes.DWORD,
                ctypes.c_uint,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostThreadMessageW.restype = wintypes.BOOL
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _win32_loop(self, bindings: dict[str, str]) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = wintypes.LPARAM
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = wintypes.DWORD

        with self._lock:
            self._thread_id = int(kernel32.GetCurrentThreadId())

        id_to_action: dict[int, str] = {}
        next_id = 100

        for action_name, spec in bindings.items():
            if not spec or not spec.strip():
                continue
            parsed = parse_hotkey_spec(spec)
            if parsed is None:
                logger.warning("Некорректный формат горячей клавиши для '%s': %r", action_name, spec)
                self._failed_bindings.append(f"{action_name} ({spec})")
                continue
            mods, vk = parsed
            hk_id = next_id
            next_id += 1
            ok = bool(user32.RegisterHotKey(None, hk_id, mods, vk))
            if ok:
                id_to_action[hk_id] = action_name
                logger.debug("Зарегистрирован хоткей [%s] -> %s (id=%d)", spec, action_name, hk_id)
            else:
                err_code = int(kernel32.GetLastError())
                logger.warning(
                    "Не удалось зарегистрировать хоткей [%s] для '%s' (Win32 GetLastError=%d — возможно, занят другой программой)",
                    spec,
                    action_name,
                    err_code,
                )
                self._failed_bindings.append(f"{spec}")

        logger.info(
            "Служба глобальных хоткеев запущена: активно %d, ошибок %d",
            len(id_to_action),
            len(self._failed_bindings),
        )
        self._ready_event.set()

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    action = id_to_action.get(int(msg.wParam))
                    if action:
                        logger.debug("Сработал глобальный хоткей -> действие '%s'", action)
                        try:
                            self._on_action(action)
                        except Exception:  # noqa: BLE001
                            logger.exception("Ошибка при вызове обработчика хоткея '%s'", action)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:  # noqa: BLE001
            logger.exception("Непредвиденная ошибка в цикле сообщений глобальных хоткеев")
        finally:
            for hk_id in id_to_action:
                user32.UnregisterHotKey(None, hk_id)
            logger.debug("Все глобальные хоткеи освобождены")
