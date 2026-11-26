"""События ввода: какие клавиши и флаги послать в Windows.

Всё, что можно посчитать заранее, считается здесь — без ``ctypes``. Обёртка в
``infrastructure/win32_input.py`` только раскладывает готовые события по структурам
``SendInput``, поэтому её можно проверить на любой платформе.

Событие — пара ``(виртуальный код, нажатие)``: ``True`` — клавиша вниз, ``False`` —
вверх.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from map_overlay.domain.keynames import VK_CONTROL

KeyEvent = tuple[int, bool]
#: Одно событие клавиатуры: код клавиши и нажата ли она.

COMBO_GAP: Final = 2.0
# Во сколько раз «нажатие» внутри сочетания считается больше отпускания: Windows
# склеивает слишком быстрое нажатие-отпускание в одно событие, и Ctrl+V не срабатывает.


def press_events(key: int) -> tuple[KeyEvent, ...]:
    """События одиночного нажатия: вниз и вверх."""
    return ((key, True), (key, False))


def combo_events(key: int) -> tuple[KeyEvent, ...]:
    """События сочетания ``Ctrl + клавиша``: Ctrl вниз, клавиша, Ctrl вверх."""
    return ((VK_CONTROL, True), (key, True), (key, False), (VK_CONTROL, False))


def held_keys(events: tuple[KeyEvent, ...]) -> frozenset[int]:
    """Какие клавиши останутся зажатыми после всех событий.

    Нужно для проверки: после любого сочетания не должно остаться зажатых клавиш —
    иначе игра получила бы «залипший» Ctrl.
    """
    held: set[int] = set()
    for key, is_down in events:
        if is_down:
            held.add(key)
        else:
            held.discard(key)
    return frozenset(held)


def set_dpi_awareness(per_monitor: Callable[[], bool], fallback: Callable[[], bool]) -> bool:
    """Включить Per-Monitor V2, а если система старая — обычную DPI-осведомлённость.

    Windows 10 умеет ``SetProcessDpiAwarenessContext``, Windows 7/8 — только
    ``SetProcessDPIAware``; ошибки в обоих случаях не должны ломать запуск, потому что
    без DPI-осведомлённости клики просто уедут на масштабе, а приложение работает.

    Args:
        per_monitor: Включить Per-Monitor V2.
        fallback: Включить обычную DPI-осведомлённость.

    Returns:
        ``True``, если режим включён (или уже был включён системой).
    """
    try:
        if per_monitor():
            return True
    except (AttributeError, OSError):
        pass
    try:
        return bool(fallback())
    except (AttributeError, OSError):
        return False
