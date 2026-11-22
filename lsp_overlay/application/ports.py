"""Порты (контракты) между прикладным слоем и инфраструктурой."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from lsp_overlay.config import Calibration, PanelTimings
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.pose import Pose


@runtime_checkable
class GamePanelPort(Protocol):
    """Левая панель редактора LSP.

    Реализация отвечает за клики, ``Ctrl+A``/``Ctrl+C``/``Ctrl+V`` и подтверждение
    ввода. Прикладной слой видит только эти четыре операции.
    """

    def is_available(self) -> bool:
        """Готова ли панель к работе (калибровка задана, окно игры найдено)."""

    def configure(
        self,
        *,
        calibration: Calibration,
        timings: PanelTimings,
        length_decimals: int,
        confirm_key: str,
    ) -> None:
        """Применяет настройки калибровки, пауз и клавиши подтверждения."""

    def read_pose(self) -> Pose:
        """Читает все шесть полей из игры."""

    def write_fields(self, values: Mapping[FieldKey, float]) -> None:
        """Вставляет значения в указанные поля (без подтверждения)."""

    def commit(self) -> None:
        """Подтверждает ввод: ЛКМ в пустое место панели и клавиша подтверждения."""
