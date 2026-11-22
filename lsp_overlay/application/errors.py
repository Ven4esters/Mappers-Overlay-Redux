"""Ошибки прикладного слоя."""

from __future__ import annotations

from lsp_overlay.domain.errors import DomainError


class PanelUnavailableError(DomainError):
    """Панель игры недоступна: нет калибровки, окно свёрнуто или буфер пуст."""


class ApplyError(DomainError):
    """Запись в панель не подтвердилась — значения откатаны."""

    def __init__(self, message: str, *, rolled_back: bool) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back
