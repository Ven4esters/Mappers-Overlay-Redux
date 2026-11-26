"""Один экземпляр оверлея: именованный мьютекс Windows.

Зачем это нужно. Два запущенных оверлея ставят два хука клавиатуры: каждая клавиша
приходит дважды, шаги удваиваются, а причина не видна — окон два, и оба выглядят
рабочими. Замок с одним именем на пользователя решает это на уровне системы: второй
экземпляр видит, что имя занято, показывает сообщение и выходит с кодом 2, ничего не
перехватывая.

Почему мьютекс, а не файл-замок: мьютекс снимается сам, когда процесс завершается,
даже если оверлей упал или его сняли через диспетчер задач. Файл-замок в этом случае
остаётся лежать и требует ручной чистки — то есть ровно того, чего пользователь не умеет.

Создание и закрытие вынесены в отдельные функции: на Linux (тесты, проверки документации)
мьютексов нет, и подменять их в тестах проще, чем поднимать Windows.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable
from typing import Final

logger = logging.getLogger(__name__)

MUTEX_NAME: Final = "Local\\MappersOverlayRedux.SingleInstance"
# Префикс ``Local\\`` — замок на сеанс пользователя: два разных пользователя на одной
# машине друг другу не мешают, а второй экземпляр того же пользователя — мешает.

ERROR_ALREADY_EXISTS: Final = 183
# Этот код возвращает ``GetLastError`` после ``CreateMutexW``, если имя уже занято.

CreateMutex = Callable[[str], "tuple[int | None, bool]"]
CloseMutex = Callable[[int], None]


def _create_mutex(name: str) -> tuple[int | None, bool]:
    """Создать мьютекс: дескриптор и признак «создан нами, имя было свободно».

    Возвращает ``(None, True)``, если мьютекс создать нельзя (не Windows, нет прав):
    тогда запуск не блокируется — лучше два экземпляра, чем ни одного.
    """
    if sys.platform != "win32":
        return None, True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        logger.warning("Мьютекс не создан, код ошибки %s", kernel32.GetLastError())
        return None, True
    return int(handle), kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _close_mutex(handle: int) -> None:
    """Закрыть дескриптор мьютекса."""
    if sys.platform != "win32":
        return
    ctypes.windll.kernel32.CloseHandle(handle)


class InstanceLock:
    """Замок «один оверлей на пользователя».

    Успешный :meth:`acquire` держит дескриптор до :meth:`release` или до завершения
    процесса: система снимет замок сама.
    """

    def __init__(
        self,
        name: str = MUTEX_NAME,
        *,
        create: CreateMutex = _create_mutex,
        close: CloseMutex = _close_mutex,
    ) -> None:
        self._name = name
        self._create = create
        self._close = close
        self._handle: int | None = None

    @property
    def held(self) -> bool:
        """Держит ли этот объект замок."""
        return self._handle is not None

    def acquire(self) -> bool:
        """Захватить замок. ``False`` — уже запущен другой экземпляр."""
        if self._handle is not None:
            return True
        handle, created = self._create(self._name)
        if handle is None:
            logger.debug("Замок недоступен: запуск продолжается без проверки экземпляров")
            return True
        if not created:
            logger.info("Замок %s занят: это второй экземпляр", self._name)
            self._close(handle)
            return False
        self._handle = handle
        logger.debug("Замок %s захвачен", self._name)
        return True

    def release(self) -> None:
        """Отпустить замок. Повторный вызов ничего не делает."""
        if self._handle is None:
            return
        self._close(self._handle)
        self._handle = None
        logger.debug("Замок %s отпущен", self._name)


def is_busy(
    name: str = MUTEX_NAME,
    *,
    create: CreateMutex = _create_mutex,
    close: CloseMutex = _close_mutex,
) -> bool:
    """Занят ли замок другим экземпляром — для ``--check-only``.

    Пробный захват тут же отпускается: проверка не должна мешать запуску.
    """
    handle, created = create(name)
    if handle is None:
        return False
    close(handle)
    return not created
