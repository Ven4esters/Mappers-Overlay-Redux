"""Ошибки предметной области.

Все ожидаемые (бизнесовые) сбои приложения наследуются от :class:`DomainError`,
чтобы UI мог отличить их от технических исключений.
"""

from __future__ import annotations


class DomainError(Exception):
    """Базовая ошибка предметной области с человекочитаемым сообщением."""


class ValidationError(DomainError):
    """Значение не прошло проверку входа (NaN, неверный диапазон, пустая строка)."""


class JumpTooLargeError(DomainError):
    """Один шаг уводит объект слишком далеко — вероятная ошибка координат."""

    def __init__(self, distance: float, limit: float) -> None:
        super().__init__(
            f"Шаг {distance:.2f} м больше лимита {limit:.1f} м за раз. "
            "Нажмите «Считать из игры», чтобы синхронизироваться."
        )
        self.distance = distance
        self.limit = limit
