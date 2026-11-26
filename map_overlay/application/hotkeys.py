"""Маршрутизация горячих клавиш: код клавиши → действие."""

from __future__ import annotations

from collections.abc import Mapping

from map_overlay.domain.actions import CTRL_ACTIONS, Action


class HotkeyRouter:
    """Превращает нажатия в действия и гасит автоповтор.

    Система повторяет ``keydown``, пока клавиша зажата. Один шаг — одно нажатие,
    поэтому автоповтор отбрасывается. Признак «свежее нажатие» приходит от
    источника клавиатуры: он видит физические события и не ошибается, даже если
    отпускание до интерфейса не дошло. Если источник признак не передаёт,
    работает прежняя проверка по своему набору зажатых клавиш.
    """

    def __init__(self, bindings: Mapping[Action, int | None]) -> None:
        self._by_key: dict[tuple[int, bool], Action] = {}
        self._pressed: set[tuple[int, bool]] = set()
        self.bind(bindings)

    def bind(self, bindings: Mapping[Action, int | None]) -> None:
        """Заменить раскладку горячих клавиш.

        Действия из :data:`CTRL_ACTIONS` срабатывают только с зажатым Ctrl: та же клавиша
        без Ctrl принадлежит игре. Поэтому ключ раскладки — пара «клавиша + Ctrl».
        """
        self._by_key = {
            (key, action in CTRL_ACTIONS): action
            for action, key in bindings.items()
            if key is not None
        }
        self._pressed.intersection_update(self._by_key)

    @property
    def bound_keys(self) -> frozenset[int]:
        """Клавиши, которые нужно перехватывать у игры."""
        return frozenset(key for key, _ctrl in self._by_key)

    @property
    def bound_ctrl_keys(self) -> frozenset[int]:
        """Клавиши, которые перехватываются только при зажатом Ctrl."""
        return frozenset(key for key, ctrl in self._by_key if ctrl)

    def is_pressed(self, vk: int) -> bool:
        """Считаем ли мы клавишу зажатой (нажатие было, отпускания не было)."""
        return any(key == vk for key, _ctrl in self._pressed)

    def forget(self, vk: int) -> None:
        """Забыть одну клавишу: отпускание потерялось, клавиша уже не зажата."""
        self._pressed = {item for item in self._pressed if item[0] != vk}

    def reset(self) -> None:
        """Забыть все зажатые клавиши (после паузы перехвата или смены раскладки)."""
        self._pressed.clear()

    def handle(
        self, vk: int, is_down: bool, fresh: bool | None = None, ctrl: bool = False
    ) -> Action | None:
        """Вернуть действие для нажатия или ``None``.

        ``fresh=False`` — автоповтор зажатой клавиши, действие не повторяется.
        ``fresh=True`` — настоящее нажатие: оно снимает возможную «зажатость»,
        оставшуюся от потерянного отпускания.
        ``ctrl`` — был ли зажат Ctrl в момент нажатия: от него зависит, чья это клавиша.
        """
        combo = (vk, ctrl)
        if not is_down:
            # Отпускание приходит без учёта Ctrl: клавиша отжата в любом сочетании.
            self._pressed = {item for item in self._pressed if item[0] != vk}
            return None
        if fresh is False:
            return None
        if fresh is None and combo in self._pressed:
            return None
        if fresh:
            self._pressed.discard(combo)
        self._pressed.add(combo)
        return self._by_key.get(combo)
