"""Вывод в консоль: кириллица при любой кодовой странице.

Зачем отдельный модуль: инструменты проекта печатают русские подписи, а кодовую страницу
консоли выбирает система. На раннере Windows это cp1252, и любая такая печать бросала
``UnicodeEncodeError``: шаг CI краснел при полностью исправной работе.
"""

from __future__ import annotations

import sys


def use_utf8_console() -> None:
    """Перевести стандартный вывод и вывод ошибок в UTF-8.

    Неподдерживаемые символы заменяются, а не прерывают печать: сообщение об ошибке
    важнее точной формы кавычек. Потоки без ``reconfigure`` (подмена в тестах) не трогаем.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
