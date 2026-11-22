"""Маршрутизация горячих клавиш: код клавиши → действие."""

from __future__ import annotations

from collections.abc import Mapping

from map_overlay.domain.actions import Action


class HotkeyRouter:
    """Превращает нажатия в действия и гасит автоповтор.

    Система повторяет ``keydown``, пока клавиша зажата. Один шаг — одно нажатие,
    поэтому повторные ``keydown`` до ``keyup`` игнорируются.
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

    def handle(self, vk: int, is_down: bool) -> Action | None:
        """Вернуть действие для нажатия или ``None``."""
        if not is_down:
            self._pressed.discard(vk)
            return None
        if vk in self._pressed:
            return None
        self._pressed.add(vk)
        return self._by_key.get(vk)
