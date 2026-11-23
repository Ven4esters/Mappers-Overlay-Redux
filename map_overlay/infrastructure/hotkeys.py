"""Глобальные горячие клавиши через низкоуровневый хук клавиатуры Windows.

Клавиши забираются у игры: нажатие на Numpad не крутит камеру и не открывает меню.
Хук живёт в отдельном потоке с собственным циклом сообщений — так Windows не рвёт
его по таймауту, а интерфейс не подвисает.

Безопасность важнее удобства: хук обязан пропускать всё, что не назначено, и никогда
не «съедать» клавиатуру из-за собственной ошибки. Поэтому решение «забирать ли
нажатие» вынесено в чистую функцию :func:`blocks_key`, а любое исключение внутри
хука превращается в пропуск клавиши.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from collections.abc import Callable, Collection
from typing import ClassVar, Final

from PySide6.QtCore import QObject, QThread, Signal

from map_overlay.domain.keynames import VK_MENU, VK_NUMLOCK, generic_vk, key_name

logger = logging.getLogger(__name__)

WH_KEYBOARD_LL: Final = 13
WM_KEYDOWN: Final = 0x0100
WM_KEYUP: Final = 0x0101
WM_SYSKEYDOWN: Final = 0x0104
WM_SYSKEYUP: Final = 0x0105
WM_QUIT: Final = 0x0012
LLKHF_INJECTED: Final = 0x10
# Флаг «клавиша послана программой», а не нажата человеком.
HOOK_TIMEOUT_MS: Final = 2000
HOOK_BLOCK: Final = 1
# Что вернуть из хука, чтобы клавиша не дошла до игры; пропуск — значение CallNextHookEx.
HOOK_PASS: Final = 0
FREEZE_LIMIT_S: Final = 20.0
# Сколько секунд клавиатура может оставаться замороженной без присмотра.
#
# Заморозка нужна на время обмена с панелью: случайное нажатие в этот момент попадает
# в поле координат и ломает значение. Она обязана сниматься сама — иначе ошибка в
# интерфейсе оставила бы пользователя без клавиатуры.

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


def blocks_key(
    *,
    vk: int,
    is_down: bool,
    bound: Collection[int],
    learning: bool,
    overlay_active: bool,
    swallowed: Collection[int],
) -> bool:
    """Забирать ли нажатие у системы.

    Правила:

    * в обычном режиме перехватываются только назначенные клавиши;
    * при записи новой привязки — любые клавиши, но только пока окно оверлея активно:
      в игре клавиатура должна работать всегда;
    * отпускание клавиши забирается лишь тогда, когда было забрано её нажатие —
      иначе игра получила бы «зажатую» клавишу.
    """
    if is_down:
        if learning:
            return overlay_active
        return vk in bound
    return vk in swallowed


class WindowsHotkeySource(QThread):
    """Поток с хуком клавиатуры.

    ``key_event`` испускается из потока хука; подписчик получает событие в своём
    потоке (Qt ставит его в очередь), поэтому интерфейс обновляется безопасно.
    """

    key_event = Signal(int, bool, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bound: frozenset[int] = frozenset()
        self._learning = False
        self._enabled = True
        self._callback: Callable[[int, bool, bool], None] | None = None
        self._thread_id = 0
        self._hook: int | None = None
        self._proc: object | None = None
        self._call_next: Callable[..., int] | None = None
        self._foreground: Callable[[], int] | None = None
        self._owner_of: Callable[..., int] | None = None
        self._own_pid: Callable[[], int] | None = None
        self._swallowed: set[int] = set()
        self._frozen = False
        self._frozen_at = 0.0
        self._alt_down = False
        self._alt_alone = False
        self._error_logged = False
        self.failed = False

    def start_listening(self, on_key: Callable[[int, bool, bool], None]) -> None:
        """Запустить хук и доставлять нажатия в ``on_key``."""
        self._callback = on_key
        self.key_event.connect(self._deliver)
        if sys.platform != "win32":
            self.failed = True
            logger.error("Горячие клавиши доступны только в Windows")
            return
        super().start()

    def freeze(self, enabled: bool) -> None:
        """Заморозить клавиатуру на время обмена с панелью.

        Пока заморозка включена, хук съедает любые **живые** клавиши: они не доходят
        ни до игры, ни до поля координат, и не считаются командами оверлея.
        Отпускания съедаются вместе с нажатиями, чтобы в игре не осталось «зажатой»
        клавиши. Клавиши, которые посылает сам оверлей (``LLKHF_INJECTED``), проходят
        как обычно — иначе обмен с панелью не смог бы нажать ``Ctrl+A`` и ``Ctrl+V``.
        """
        if enabled == self._frozen:
            return
        self._frozen = enabled
        self._frozen_at = time.monotonic()
        if enabled:
            logger.info("Клавиатура заморожена на время обмена с панелью")
        else:
            self._swallowed.clear()
            logger.info("Клавиатура разморожена")

    def _freeze_expired(self) -> bool:
        """Не висит ли заморозка дольше положенного: тогда снимаем её сами."""
        if not self._frozen:
            return False
        if time.monotonic() - self._frozen_at < FREEZE_LIMIT_S:
            return False
        self._frozen = False
        self._swallowed.clear()
        logger.warning(
            "Заморозка клавиатуры снята принудительно после %.0f с: интерфейс не разморозил её",
            FREEZE_LIMIT_S,
        )
        return True

    def stop_listening(self) -> None:
        """Остановить хук и дождаться потока."""
        self._frozen = False
        self._swallowed.clear()
        if sys.platform == "win32" and self._thread_id:
            windll = ctypes.windll
            windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self.isRunning():
            self.wait(HOOK_TIMEOUT_MS)

    def configure(self, *, bound_keys: Collection[int], learning: bool) -> None:
        """Сказать хуку, какие клавиши перехватывать."""
        self._bound = frozenset(bound_keys)
        self._learning = learning

    @property
    def enabled(self) -> bool:
        """Включён ли перехват (для проверок и журнала)."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Включить или приостановить перехват.

        Выключенный хук пропускает все клавиши как есть: это аварийный выход, если
        игра перестала получать клавиатуру.
        """
        self._enabled = enabled
        if not enabled:
            self._swallowed.clear()
            self._frozen = False

    def num_lock_enabled(self) -> bool | None:
        """Включён ли NumLock."""
        if sys.platform != "win32":
            return None
        return bool(ctypes.windll.user32.GetKeyState(VK_NUMLOCK) & 1)

    def key_down(self, vk: int) -> bool:
        """Зажата ли клавиша прямо сейчас.

        Нужно как страховка: если ``keyup`` потерялся (хук переставили, перехват
        выключили), удержание не должно продолжать двигать предмет бесконечно.
        """
        if sys.platform != "win32":
            return False
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def is_available(self) -> bool:
        """Установлен ли хук."""
        return not self.failed and sys.platform == "win32"

    def run(self) -> None:
        """Установить хук и крутить цикл сообщений потока."""
        windll = ctypes.windll
        user32 = windll.user32
        kernel32 = windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        self._bind_prototypes(user32)
        self._proc = _HOOK_PROC(self._handle)
        install = user32.SetWindowsHookExW
        self._hook = install(WH_KEYBOARD_LL, self._proc, None, 0)
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

    def _bind_prototypes(self, user32: object) -> None:
        """Задать типы аргументов: без них 64-битные значения теряются."""
        install = user32.SetWindowsHookExW  # type: ignore[attr-defined]
        install.argtypes = [ctypes.c_int, _HOOK_PROC, ctypes.c_void_p, ctypes.c_ulong]
        install.restype = ctypes.c_void_p
        call_next = user32.CallNextHookEx  # type: ignore[attr-defined]
        call_next.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
        call_next.restype = ctypes.c_ssize_t
        foreground = user32.GetForegroundWindow  # type: ignore[attr-defined]
        foreground.argtypes = []
        foreground.restype = ctypes.c_void_p
        owner = user32.GetWindowThreadProcessId  # type: ignore[attr-defined]
        owner.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        owner.restype = ctypes.c_ulong
        self._call_next = call_next
        self._foreground = foreground
        self._owner_of = owner
        self._own_pid = ctypes.windll.kernel32.GetCurrentProcessId

    def _deliver(self, vk: int, is_down: bool, fresh: bool) -> None:
        if self._callback is not None:
            self._callback(vk, is_down, fresh)

    def _handle(self, code: int, wparam: int, lparam: int) -> int:
        try:
            return self._decide(code, wparam, lparam)
        except Exception:
            if not self._error_logged:
                self._error_logged = True
                logger.exception("Ошибка в хуке клавиатуры: клавиши пропускаем как есть")
            return self._pass_through(code, wparam, lparam)

    def _decide(self, code: int, wparam: int, lparam: int) -> int:
        if code < 0:
            return self._pass_through(code, wparam, lparam)
        data = ctypes.cast(lparam, ctypes.POINTER(_KeyboardHookData)).contents
        vk = generic_vk(int(data.vk))
        injected = bool(int(data.flags) & LLKHF_INJECTED)
        is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = wparam in (WM_KEYUP, WM_SYSKEYUP)
        if not (is_down or is_up):
            return self._pass_through(code, wparam, lparam)
        self._freeze_expired()
        if self._frozen and self._enabled and not injected:
            return self._swallow(is_down, vk)
        self._observe_alt(vk, is_down, injected)
        block = self._enabled and blocks_key(
            vk=vk,
            is_down=is_down,
            bound=self._bound,
            learning=self._learning,
            overlay_active=self._learning and self._foreground_is_ours(),
            swallowed=self._swallowed,
        )
        fresh = is_down and block and vk not in self._swallowed
        if is_down and block:
            self._swallowed.add(vk)
        elif is_up:
            self._swallowed.discard(vk)
        if not block:
            if is_down and vk in self._bound:
                logger.debug("Клавиша %s пропущена: перехват выключен", key_name(vk))
            return self._pass_through(code, wparam, lparam)
        if fresh:
            logger.debug("Хук забрал клавишу %s", key_name(vk))
        self.key_event.emit(vk, is_down, fresh)
        return HOOK_BLOCK

    def _swallow(self, is_down: bool, vk: int) -> int:
        """Съесть живую клавишу на время обмена с панелью.

        Клавиши, которые посылает сам оверлей (``LLKHF_INJECTED``), сюда не попадают:
        это ``Ctrl+A`` и ``Ctrl+V``, которыми пишутся значения. Отпускания съедаются
        вместе с нажатиями, чтобы в игре не осталось «зажатой» клавиши.
        """
        if is_down:
            self._swallowed.add(vk)
        else:
            self._swallowed.discard(vk)
        return HOOK_BLOCK

    def _observe_alt(self, vk: int, is_down: bool, injected: bool = False) -> None:
        """Заметить одиночное нажатие Alt — им переключается режим высоты.

        Alt не забирается у игры: он проходит как обычно. Переключателем считается
        только одиночное нажатие, а комбинация (``Alt+Tab``, ``Alt+F4``,
        ``Alt+Num 8``) — нет, иначе режим менялся бы во время обычной работы.

        Клавиши, которые оверлей посылает сам (``Ctrl+A``, ``Ctrl+V``), не считаются
        нажатием человека: иначе во время шага любое нажатие Alt выглядело бы
        комбинацией, и режим не переключался бы.
        """
        if injected:
            return
        if vk == VK_MENU:
            if is_down:
                if not self._alt_down:
                    self._alt_down = True
                    self._alt_alone = True
                return
            self._alt_down = False
            alone = self._alt_alone
            self._alt_alone = False
            if alone and self._enabled and not self._learning:
                logger.info("Alt нажат один: переключаю режим высоты")
                self.key_event.emit(VK_MENU, True, True)
            return
        if self._alt_down:
            self._alt_alone = False

    def _foreground_is_ours(self) -> bool:
        """Активно ли окно оверлея (а не игра или другая программа)."""
        if self._foreground is None or self._owner_of is None or self._own_pid is None:
            return False
        pid = ctypes.c_ulong()
        self._owner_of(self._foreground(), ctypes.byref(pid))
        return int(pid.value) == int(self._own_pid())

    def _pass_through(self, code: int, wparam: int, lparam: int) -> int:
        """Пропустить клавишу дальше: вернуть то, что вернул бы следующий хук."""
        if self._call_next is None:
            return HOOK_PASS
        return int(self._call_next(None, code, wparam, lparam))
