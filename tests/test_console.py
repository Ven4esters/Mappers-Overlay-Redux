"""Вывод в консоль: кириллица не роняет запуск при узкой кодовой странице."""

from __future__ import annotations

import io
import sys

import pytest
from map_overlay.console import use_utf8_console


def test_console_switches_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    """После переключения кириллица печатается даже в потоке с cp1252."""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    use_utf8_console()
    print("Экземпляр: не запущен")

    assert "Экземпляр" in buffer.getvalue().decode("utf-8")


def test_console_skips_streams_without_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменённый поток без reconfigure не мешает остальным."""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", "не поток")

    use_utf8_console()

    assert stream.encoding == "utf-8"
