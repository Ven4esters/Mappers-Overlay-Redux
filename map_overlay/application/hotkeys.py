"""Маршрутизация горячих клавиш: код клавиши → действие."""

from __future__ import annotations

from collections.abc import Mapping

from map_overlay.domain.actions import Action


class HotkeyRouter:
    """Превращает нажатия в действия и гасит автоповтор.

    Система повторяет ``keydown``, пока клавиша зажата. Один шаг — одно нажатие,
    поэтому автоповтор отбрасывается. Признак «свежее нажатие» приходит от
    источника клавиатуры: он видит физические события и не ошибается, даже если
    отпускание до интерфейса не дошло. Если источник признак не передаёт,
    работает прежняя проверка по своему набору зажатых клавиш.
    """

    def __init__(self, bindings: Mapping[Action, int | None]) -> None:
        self._by_key: dict[int, Action] = {}
        self._pressed: set[int] = set()
        self.bind(bindings)

    def bind(self, bindings: Mapping[Action, int | None]) -> None:
        """Заменить раскладку горячих клавиш."""
        self._by_key = {key: action for action, key in bindings.items() if key is not None}

    @property
    def bound_keys(self) -> frozenset[int]:
        """Клавиши, которые нужно перехватывать у игры."""
        return frozenset(self._by_key)

    def is_pressed(self, vk: int) -> bool:
        """Считаем ли мы клавишу зажатой (нажатие было, отпускания не было)."""
        return vk in self._pressed

    def forget(self, vk: int) -> None:
        """Забыть одну клавишу: отпускание потерялось, клавиша уже не зажата."""
        self._pressed.discard(vk)

    def reset(self) -> None:
        """Забыть все зажатые клавиши (после паузы перехвата или смены раскладки)."""
        self._pressed.clear()

    def handle(self, vk: int, is_down: bool, fresh: bool | None = None) -> Action | None:
        """Вернуть действие для нажатия или ``None``.

        ``fresh=False`` — автоповтор зажатой клавиши, действие не повторяется.
        ``fresh=True`` — настоящее нажатие: оно снимает возможную «зажатость»,
        оставшуюся от потерянного отпускания.
        """
        if not is_down:
            self._pressed.discard(vk)
            return None
        if fresh is False:
            return None
        if fresh is None and vk in self._pressed:
            return None
        if fresh:
            self._pressed.discard(vk)
        self._pressed.add(vk)
        return self._by_key.get(vk)
