"""Самопроверка «доходит ли ввод до игры».

Пользователь видит «координаты меняются в программе, но не в игре» — значит, клик
или вставка не попадают в панель LSP. Диагностика отвечает на три вопроса:
читается ли поле, попадает ли клик в окно игры и подтверждается ли запись.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lsp_overlay.application.errors import PanelUnavailableError
from lsp_overlay.application.ports import GamePanelPort
from lsp_overlay.domain.errors import DomainError
from lsp_overlay.domain.fields import FieldKey
from lsp_overlay.domain.formatting import format_length
from lsp_overlay.domain.safety import LENGTH_TOLERANCE

LOGGER = logging.getLogger(__name__)
PROBE_DELTA = 0.01


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """Результат самопроверки в человекочитаемом виде."""

    read_ok: bool
    write_ok: bool
    message: str

    @property
    def all_ok(self) -> bool:
        """Ввод работает полностью."""
        return self.read_ok and self.write_ok


def run_diagnostics(panel: GamePanelPort) -> DiagnosticReport:
    """Проверяет чтение и запись, не сдвигая проп в итоге.

    Значение поля X меняется на контрольную величину (1 см) и возвращается назад:
    так видно, принимает ли панель вставку. Итоговое состояние не меняется.
    """
    if not panel.is_available():
        return DiagnosticReport(
            read_ok=False,
            write_ok=False,
            message=(
                "Панель недоступна: не задана калибровка или ввод запрещён системой. "
                "Проверьте «Калибровку» и права администратора."
            ),
        )
    try:
        pose = panel.read_pose()
    except DomainError as error:
        return DiagnosticReport(
            read_ok=False,
            write_ok=False,
            message=(
                f"Поле X не читается: {error}. Клик не попадает в панель — "
                "перекалибруйте точки или отключите масштабирование экрана."
            ),
        )

    probe = pose.x + PROBE_DELTA
    try:
        panel.write_fields({FieldKey.X: probe})
        accepted = panel.read_pose()
        taken = abs(accepted.x - probe) <= LENGTH_TOLERANCE
    except PanelUnavailableError as error:
        return DiagnosticReport(
            read_ok=True,
            write_ok=False,
            message=(
                f"Чтение работает, запись — нет: {error}. "
                "Частая причина — клиент запущен от администратора, а оверлей нет."
            ),
        )
    finally:
        _restore(panel, pose.x)

    LOGGER.info("Диагностика: чтение ok, запись %s", "ok" if taken else "сбой")
    if taken:
        return DiagnosticReport(
            read_ok=True,
            write_ok=True,
            message=(
                "Ввод работает: панель приняла контрольное значение и координата вернулась "
                "обратно. Если проп стоит на месте — нажмите «Сохранить F»."
            ),
        )
    return DiagnosticReport(
        read_ok=True,
        write_ok=False,
        message=(
            "Вставка не приживается: панель показала "
            f"{format_length(accepted.x)} вместо {format_length(probe)}. "
            "Проверьте, что клик попадает в поле, что клиент не запущен от администратора "
            "(тогда запустите оверлей тоже от администратора) и увеличьте паузы."
        ),
    )


def _restore(panel: GamePanelPort, value: float) -> None:
    """Возвращает прежнее значение X, что бы ни случилось."""
    try:
        panel.write_fields({FieldKey.X: value})
    except Exception:  # noqa: BLE001 - восстановление best-effort, ошибка уже обработана
        LOGGER.exception("Не удалось вернуть прежнее значение X после диагностики")
