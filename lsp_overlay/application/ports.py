"""Порты (контракты) между прикладным слоем и инфраструктурой."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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

    def read_fields(self, keys: Sequence[FieldKey]) -> dict[FieldKey, float]:
        """Читает только указанные поля — для проверки записи."""

    def write_fields(self, values: Mapping[FieldKey, float]) -> None:
        """Вставляет значения в указанные поля (без подтверждения)."""

    def commit(self) -> None:
        """Подтверждает ввод: ЛКМ в пустое место панели и клавиша подтверждения."""

    def tap_key(self, key: str) -> None:
        """Нажимает одиночную клавишу в окне игры (копирование и удаление копии)."""


@runtime_checkable
class KeyStatePort(Protocol):
    """Состояние клавиш, доступное без фокуса окна (живой режим)."""

    def is_ready(self) -> bool:
        """Доступно ли чтение состояния клавиш."""

    def is_down(self, vk_code: int) -> bool:
        """Нажата ли клавиша с виртуальным кодом Windows."""

    def num_lock_enabled(self) -> bool:
        """Включён ли NumLock (иначе Numpad шлёт не цифры)."""


@runtime_checkable
class KeyHookPort(Protocol):
    """Глобальный перехват Numpad: клавиши гасятся и не доходят до игры."""

    def is_available(self) -> bool:
        """Есть ли возможность перехватывать клавиши вне окна оверлея."""

    def start(self, callback: Callable[[int, bool], None]) -> bool:
        """Ставит хук; ``callback(vk_code, pressed)`` зовётся на нажатие и отпускание."""

    def stop(self) -> None:
        """Снимает хук."""
