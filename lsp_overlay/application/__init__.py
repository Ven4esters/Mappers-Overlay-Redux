"""Прикладной слой: сценарии использования без привязки к Qt и Win32."""

from lsp_overlay.application.diagnostics import DiagnosticReport, run_diagnostics
from lsp_overlay.application.errors import ApplyError, PanelUnavailableError
from lsp_overlay.application.ports import GamePanelPort
from lsp_overlay.application.session import MappingSession
from lsp_overlay.application.writer import ApplyResult, FieldWriter

__all__ = [
    "ApplyError",
    "DiagnosticReport",
    "ApplyResult",
    "FieldWriter",
    "GamePanelPort",
    "MappingSession",
    "PanelUnavailableError",
    "run_diagnostics",
]
