"""Один экземпляр оверлея: именованный мьютекс и поведение второго запуска."""

from __future__ import annotations

import sys
from collections.abc import Iterator

import map_overlay.main as app_main
import pytest
from map_overlay.infrastructure import single_instance
from map_overlay.infrastructure.single_instance import InstanceLock, is_busy


class FakeMutex:
    """Мьютекс в памяти: помнит, что создан, и сколько раз закрыт."""

    def __init__(self, *, busy: bool = False, handle: int | None = 7) -> None:
        self.busy = busy
        self.handle = handle
        self.created: list[str] = []
        self.closed: list[int] = []

    def create(self, name: str) -> tuple[int | None, bool]:
        self.created.append(name)
        return self.handle, not self.busy

    def close(self, handle: int) -> None:
        self.closed.append(handle)


def make_lock(fake: FakeMutex, name: str = "test-lock") -> InstanceLock:
    return InstanceLock(name, create=fake.create, close=fake.close)


def test_free_lock_is_taken_and_held() -> None:
    fake = FakeMutex()
    lock = make_lock(fake)
    assert lock.acquire() is True
    assert lock.held is True
    assert fake.created == ["test-lock"]
    assert fake.closed == []


def test_busy_lock_is_not_taken_and_rejected_handle_is_closed() -> None:
    """Второй экземпляр не стартует, а дескриптор, который он получил, закрывается."""
    fake = FakeMutex(busy=True)
    lock = make_lock(fake)
    assert lock.acquire() is False
    assert lock.held is False
    assert fake.closed == [7]


def test_repeated_acquire_does_not_create_second_mutex() -> None:
    fake = FakeMutex()
    lock = make_lock(fake)
    assert lock.acquire() is True
    assert lock.acquire() is True
    assert fake.created == ["test-lock"]


def test_release_closes_handle_once() -> None:
    fake = FakeMutex()
    lock = make_lock(fake)
    lock.acquire()
    lock.release()
    lock.release()
    assert fake.closed == [7]
    assert lock.held is False


def test_acquire_after_release_creates_mutex_again() -> None:
    fake = FakeMutex()
    lock = make_lock(fake)
    lock.acquire()
    lock.release()
    assert lock.acquire() is True
    assert fake.created == ["test-lock", "test-lock"]


def test_unavailable_mutex_does_not_block_start() -> None:
    """Нет мьютекса (не Windows, нет прав) — лучше запуститься, чем не запуститься."""
    fake = FakeMutex(handle=None)
    lock = make_lock(fake)
    assert lock.acquire() is True
    assert lock.held is False
    assert fake.closed == []


def test_is_busy_reports_and_closes_probe_handle() -> None:
    fake = FakeMutex(busy=True)
    assert is_busy("probe", create=fake.create, close=fake.close) is True
    assert fake.closed == [7]


def test_is_busy_is_false_when_free() -> None:
    fake = FakeMutex()
    assert is_busy("probe", create=fake.create, close=fake.close) is False
    assert fake.closed == [7]


def test_is_busy_is_false_without_mutex_support() -> None:
    fake = FakeMutex(handle=None)
    assert is_busy("probe", create=fake.create, close=fake.close) is False
    assert fake.closed == []


def test_real_mutex_behaves_by_platform() -> None:
    """Настоящий замок: на Windows он держится и блокирует второй, на Linux — нет.

    Тест один на обе платформы нарочно: на Linux он фиксирует «проверка отключена
    штатно», а на Windows — что мьютекс действительно создаётся. Именно эта проверка
    падала в джобе Windows, когда тест был написан только под Linux.
    """
    first = InstanceLock("Local\\MappersOverlayRedux.Tests")
    second = InstanceLock("Local\\MappersOverlayRedux.Tests")
    try:
        assert first.acquire() is True
        assert first.held is (sys.platform == "win32")
        assert second.acquire() is (sys.platform != "win32")
    finally:
        first.release()
        second.release()


def test_second_instance_exits_with_code_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """Занятый замок: второй экземпляр не создаёт окно и выходит с кодом 2."""

    class BusyLock:
        def acquire(self) -> bool:
            return False

        def release(self) -> None:
            raise AssertionError("Отпускать нечего: замок не наш")

    reported: list[str] = []
    started: list[bool] = []

    monkeypatch.setattr(app_main, "InstanceLock", BusyLock)
    monkeypatch.setattr(app_main, "_report_already_running", lambda: reported.append("busy") or 2)
    monkeypatch.setattr(app_main, "_run_locked", lambda: started.append(True) or 0)

    assert app_main._run_window() == 2
    assert reported == ["busy"]
    assert started == []


def test_window_is_started_when_lock_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свободный замок: запуск идёт дальше, а замок отпускается на выходе."""
    released: list[bool] = []

    class FreeLock:
        def acquire(self) -> bool:
            return True

        def release(self) -> None:
            released.append(True)

    monkeypatch.setattr(app_main, "InstanceLock", FreeLock)
    monkeypatch.setattr(app_main, "_run_locked", lambda: 0)

    assert app_main._run_window() == 0
    assert released == [True]


@pytest.fixture(autouse=True)
def _restore_mutex_functions() -> Iterator[None]:
    """Подмены в тестах не должны утекать в соседние проверки."""
    keep = (single_instance._create_mutex, single_instance._close_mutex)
    yield
    single_instance._create_mutex, single_instance._close_mutex = keep
