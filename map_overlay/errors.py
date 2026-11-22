"""Иерархия ошибок приложения.

Все ошибки, которые видит пользователь, наследуются от :class:`AppError`, поэтому
граница UI может ловить одно семейство исключений и показывать текст как есть.
"""

from __future__ import annotations


class AppError(Exception):
    """Ошибка с текстом, понятным пользователю."""


class DomainError(AppError):
    """Ошибка предметной области (данные, а не окружение)."""


class ValidationError(DomainError):
    """Значение не прошло проверку: шаг, точность, координата."""


class ParseError(DomainError):
    """Из текста панели не удалось получить число."""


class ConfigError(AppError):
    """Файл настроек не читается или содержит недопустимые значения."""


class ApplicationError(AppError):
    """Сценарий не может быть выполнен."""


class NotCalibratedError(ApplicationError):
    """Не заданы точки полей панели."""


class PoseNotCapturedError(ApplicationError):
    """Координаты ещё не считаны из панели."""


class PanelRejectedError(ApplicationError):
    """Панель не приняла записанное значение."""


class InputError(ApplicationError):
    """Win32 не выполнил клик или нажатие клавиши."""


class ClipboardError(ApplicationError):
    """Буфер обмена недоступен."""


class UnsupportedPlatformError(ApplicationError):
    """Действие доступно только в Windows."""
