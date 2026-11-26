"""Инфраструктура: буфер обмена, часы, Win32-заглушки и сообщения об ошибках."""

from __future__ import annotations

import sys

import pyperclip
import pytest
from map_overlay.errors import ClipboardError, UnsupportedPlatformError
from map_overlay.infrastructure.clipboard import SystemClipboard
from map_overlay.infrastructure.clock import SystemClock
from map_overlay.infrastructure.win32_input import WindowsInput, enable_dpi_awareness


def test_clipboard_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = {"text": ""}
    monkeypatch.setattr(pyperclip, "copy", lambda text: storage.update(text=text))
    monkeypatch.setattr(pyperclip, "paste", lambda: storage["text"])
    clipboard = SystemClipboard()
    clipboard.set("1845.000")
    assert clipboard.get() == "1845.000"


def test_clipboard_failure_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> str:
        raise pyperclip.PyperclipException("нет доступа")

    monkeypatch.setattr(pyperclip, "paste", broken)
    with pytest.raises(ClipboardError, match="Буфер обмена недоступен"):
        SystemClipboard().get()


def test_clipboard_write_failure_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_text: str) -> None:
        raise pyperclip.PyperclipException("нет доступа")

    monkeypatch.setattr(pyperclip, "copy", broken)
    with pytest.raises(ClipboardError, match="Не удалось записать"):
        SystemClipboard().set("1")


def test_clock_ignores_zero_pause() -> None:
    SystemClock().sleep(0)
    SystemClock().sleep(0.001)


@pytest.mark.skipif(sys.platform == "win32", reason="проверяем поведение вне Windows")
def test_windows_input_refuses_other_platforms() -> None:
    with pytest.raises(UnsupportedPlatformError):
        WindowsInput()


@pytest.mark.skipif(sys.platform == "win32", reason="DPI включается только в Windows")
def test_dpi_awareness_is_false_off_windows() -> None:
    assert enable_dpi_awareness() is False


@pytest.mark.skipif(sys.platform == "win32", reason="проверяем поведение вне Windows")
def test_windows_hotkey_source_refuses_other_platforms() -> None:
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    events: list[tuple[int, bool]] = []
    source = WindowsHotkeySource()
    source.start_listening(lambda vk, is_down, fresh: events.append((vk, is_down)))
    assert source.failed is True
    assert source.is_available() is False
    assert source.num_lock_enabled() is None
    source.stop_listening()
    assert events == []


@pytest.mark.skipif(sys.platform == "win32", reason="проверяем поведение вне Windows")
def test_modifier_state_off_windows_is_off() -> None:
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    source = WindowsHotkeySource()
    assert source.key_down(0x68) is False


def test_hook_decides_fresh_press_and_autorepeat(
    qt_app: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Решение хука: первое нажатие свежее, автоповтор — нет, отпускание — нет."""
    import ctypes

    from map_overlay.infrastructure.hotkeys import (
        WM_KEYDOWN,
        WM_KEYUP,
        WindowsHotkeySource,
        _KeyboardHookData,
    )

    source = WindowsHotkeySource()
    source._bound = frozenset({0x68})
    source._enabled = True
    source._call_next = lambda *args: 0
    events: list[tuple[int, bool, bool]] = []
    source.key_event.connect(lambda vk, down, fresh: events.append((vk, down, fresh)))
    data = _KeyboardHookData(vk=0x68, scan=0, flags=0, time=0, extra=None)
    lparam = ctypes.addressof(data)

    with caplog.at_level("DEBUG"):
        assert source._decide(0, WM_KEYDOWN, lparam) == 1
        assert source._decide(0, WM_KEYDOWN, lparam) == 1
        assert source._decide(0, WM_KEYUP, lparam) == 1
    assert events == [(0x68, True, True), (0x68, True, False), (0x68, False, False)]
    # В журнал попадает только само нажатие: автоповтор и отпускание молчат.
    # Уровень DEBUG, а не INFO: поток хука не должен ждать записи на диск.
    assert caplog.text.count("Хук забрал клавишу Num 8") == 1


class _HookHarness:
    """Хук с поддельным событием клавиатуры: проверяем решение без Windows."""

    def __init__(self, bound: tuple[int, ...] = (0x68,), learning: bool = False) -> None:
        import ctypes

        from map_overlay.infrastructure.hotkeys import WindowsHotkeySource, _KeyboardHookData

        self.ctypes = ctypes
        self.source = WindowsHotkeySource()
        self.source._bound = frozenset(bound)
        self.source._learning = learning
        self.source._enabled = True
        self.source._call_next = lambda *args: 0
        self.events: list[tuple[int, bool, bool]] = []
        self.source.key_event.connect(lambda vk, down, fresh: self.events.append((vk, down, fresh)))
        self._data = _KeyboardHookData(vk=0, scan=0, flags=0, time=0, extra=None)

    def send(self, vk: int, is_down: bool, *, injected: bool = False) -> int:
        """Отправить нажатие или отпускание и вернуть решение хука."""
        from map_overlay.infrastructure.hotkeys import LLKHF_INJECTED, WM_KEYDOWN, WM_KEYUP

        self._data.vk = vk
        self._data.flags = LLKHF_INJECTED if injected else 0
        message = WM_KEYDOWN if is_down else WM_KEYUP
        return int(self.source._decide(0, message, self.ctypes.addressof(self._data)))


def test_single_alt_tap_is_reported_as_toggle() -> None:
    hook = _HookHarness()
    # Alt не забирается у игры: отпускание и нажатие проходят как есть.
    assert hook.send(0x12, True) == 0
    assert hook.send(0x12, False) == 0
    assert hook.events == [(0x12, True, True)]


def test_alt_with_another_key_is_a_combination() -> None:
    hook = _HookHarness()
    hook.send(0x12, True)
    hook.send(0x68, True)
    hook.send(0x68, False)
    hook.send(0x12, False)
    assert (0x12, True, True) not in hook.events


def test_alt_tap_is_ignored_while_learning() -> None:
    hook = _HookHarness(learning=True)
    hook.send(0x12, True)
    hook.send(0x12, False)
    assert hook.events == []


def test_alt_tap_is_ignored_when_interception_is_off() -> None:
    hook = _HookHarness()
    hook.source._enabled = False
    hook.send(0x12, True)
    hook.send(0x12, False)
    assert hook.events == []


def test_single_alt_tap_arrives_with_a_side_code() -> None:
    """Настоящий хук присылает 0xA4 (левый Alt) — переключатель должен сработать."""
    hook = _HookHarness()
    hook.send(0xA4, True)
    hook.send(0xA4, False)
    assert hook.events == [(0x12, True, True)]


def test_injected_keys_do_not_break_the_alt_tap() -> None:
    """Ctrl+A/Ctrl+V оверлея не превращают нажатие Alt в комбинацию."""
    hook = _HookHarness()
    hook.send(0xA4, True)
    hook.send(0x11, True, injected=True)
    hook.send(0x41, True, injected=True)
    hook.send(0x41, False, injected=True)
    hook.send(0x11, False, injected=True)
    hook.send(0xA4, False)
    assert hook.events == [(0x12, True, True)]


def test_side_codes_are_swallowed_for_bound_keys() -> None:
    """Горячая клавиша на Ctrl сработает, хотя хук присылает 0xA2."""
    hook = _HookHarness(bound=(0x11,))
    assert hook.send(0xA2, True) == 1
    assert hook.events == [(0x11, True, True)]


def test_frozen_hook_swallows_every_key() -> None:
    """Пока идёт обмен с панелью, клавиши не доходят ни до игры, ни до интерфейса."""
    hook = _HookHarness(bound=(0x68,))
    hook.source.freeze(True)
    assert hook.send(0x68, True) == 1
    assert hook.send(0x68, False) == 1
    assert hook.send(0x41, True) == 1
    assert hook.send(0x41, False) == 1
    assert hook.events == []


def test_frozen_hook_does_not_toggle_the_mode() -> None:
    """Alt во время обмена не переключает режим: клавиатура закрыта."""
    hook = _HookHarness()
    hook.source.freeze(True)
    hook.send(0xA4, True)
    hook.send(0xA4, False)
    assert hook.events == []


def test_unfrozen_hook_works_again() -> None:
    hook = _HookHarness(bound=(0x68,))
    hook.source.freeze(True)
    hook.send(0x68, True)
    hook.source.freeze(False)
    assert hook.send(0x68, True) == 1
    assert hook.events == [(0x68, True, True)]


def test_freeze_is_lifted_after_the_limit() -> None:
    """Забытая заморозка снимается сама: клавиатура не может остаться мертвой."""
    hook = _HookHarness()
    hook.source.freeze(True)
    hook.source._frozen_at -= 60.0
    assert hook.send(0x41, True) == 0
    assert hook.source._frozen is False


def test_frozen_hook_passes_its_own_keys_through() -> None:
    """Ctrl+A/Ctrl+V оверлея обязаны дойти до панели, даже когда клавиатура заморожена.

    Именно на этом сломался 1.4.1: заморозка съедала собственные клавиши, поле не
    менялось, а проверка читала буфер, который оверлей сам же и положил.
    """
    hook = _HookHarness()
    hook.source.freeze(True)
    assert hook.send(0x11, True, injected=True) == 0  # Ctrl
    assert hook.send(0x41, True, injected=True) == 0  # A
    assert hook.send(0x41, False, injected=True) == 0
    assert hook.send(0x56, True, injected=True) == 0  # V
    assert hook.send(0x11, False, injected=True) == 0
    assert hook.events == []


def test_frozen_hook_still_blocks_live_keys_next_to_its_own() -> None:
    hook = _HookHarness()
    hook.source.freeze(True)
    assert hook.send(0x11, True, injected=True) == 0
    assert hook.send(0x41, True) == 1
    assert hook.send(0x41, False) == 1


def test_emergency_stop_lifts_the_freeze() -> None:
    """Галочка «Перехватывать клавиши» сильнее заморозки: клавиатура оживает сразу.

    Иначе при зависшем обмене с панелью пользователь снимал галочку, а клавиши
    продолжали съедаться до истечения :data:`FREEZE_LIMIT_S`.
    """
    hook = _HookHarness(bound=(0x68,))
    hook.source.freeze(True)
    hook.source.set_enabled(False)
    assert hook.source._frozen is False
    assert hook.send(0x41, True) == 0


def test_frozen_hook_passes_keys_when_interception_is_off() -> None:
    hook = _HookHarness(bound=(0x68,))
    hook.source._enabled = False
    hook.source.freeze(True)
    assert hook.send(0x41, True) == 0
    assert hook.source._frozen is True


def test_foreground_window_is_checked_only_while_learning() -> None:
    """Обычное нажатие не тратит два вызова Win32 на определение активного окна."""
    calls: list[bool] = []
    hook = _HookHarness(bound=(0x68,))
    hook.source._foreground_is_ours = lambda: calls.append(True) or False
    hook.send(0x68, True)
    assert calls == []
    hook.source._learning = True
    hook.send(0x68, True)
    assert calls == [True]


# --- чистые события ввода и тонкая обёртка Win32 --------------------------


def test_combo_press_and_release_leave_no_key_held() -> None:
    """Сочетание и одиночное нажатие: ни одна клавиша не остаётся зажатой."""
    from map_overlay.domain.input_events import combo_events, held_keys, press_events

    assert press_events(0x46) == ((0x46, True), (0x46, False))
    assert combo_events(0x41) == ((0x11, True), (0x41, True), (0x41, False), (0x11, False))
    assert held_keys(press_events(0x46)) == frozenset()
    assert held_keys(combo_events(0x41)) == frozenset()
    # Ctrl идёт первым и отпускается последним — иначе игра увидит «Ctrl+клик».
    assert combo_events(0x41)[0][0] == 0x11
    assert combo_events(0x41)[-1][0] == 0x11


@pytest.mark.parametrize(
    ("per_monitor", "fallback", "expected"),
    [
        (lambda: True, lambda: False, True),
        (lambda: False, lambda: True, True),
        (lambda: False, lambda: False, False),
    ],
)
def test_dpi_awareness_uses_the_first_working_api(
    per_monitor: object, fallback: object, expected: bool
) -> None:
    """Сначала Per-Monitor V2, при отказе — обычная DPI-осведомлённость."""
    from map_overlay.domain.input_events import set_dpi_awareness

    assert set_dpi_awareness(per_monitor, fallback) is expected  # type: ignore[arg-type]


def test_dpi_awareness_survives_missing_api() -> None:
    """Старая Windows: первая функция недоступна, вторая отвечает — режим включён."""
    from map_overlay.domain.input_events import set_dpi_awareness

    def missing() -> bool:
        raise AttributeError("нет такого API")

    assert set_dpi_awareness(missing, lambda: True) is True


def test_dpi_awareness_reports_failure_instead_of_raising() -> None:
    """Обе функции сломались — запуск не падает, просто клики будут в логических точках."""
    from map_overlay.domain.input_events import set_dpi_awareness

    def broken() -> bool:
        raise OSError("система не дала")

    assert set_dpi_awareness(broken, broken) is False


class _FakeUser32:
    """Поддельный ``user32``: записывает, что и куда послали."""

    def __init__(self) -> None:
        self.sent: list[int] = []
        self.cursor = (300, 120)
        self.click_batches: list[tuple[int, ...]] = []
        self.modifiers: dict[int, int] = {}
        self.cursor_ok = True
        self.move_ok = True
        self.send_ok = True

        # Заглушки для настройки argtypes в конструкторе класса.
        self.GetCursorPos = self._get_cursor_pos
        self.SendInput = self._send_input
        self.SetCursorPos = self._set_cursor_pos
        self.GetAsyncKeyState = self._get_async_key_state

    def _get_cursor_pos(self, pointer: object) -> int:
        import ctypes

        from map_overlay.infrastructure.win32_input import _NativePoint

        if not self.cursor_ok:
            return 0
        point = ctypes.cast(pointer, ctypes.POINTER(_NativePoint)).contents
        point.x, point.y = self.cursor
        return 1

    def _send_input(self, count: int, payload: object, size: int) -> int:
        if not self.send_ok:
            return count - 1
        self.click_batches.append(
            tuple(getattr(payload[index].data.keyboard, "vk", 0) for index in range(count))
        )
        return count

    def _set_cursor_pos(self, x: int, y: int) -> int:
        return int(self.move_ok)

    def _get_async_key_state(self, vk: int) -> int:
        return self.modifiers.get(vk, 0)


def _fake_input(user32: _FakeUser32) -> object:
    """``WindowsInput`` с поддельным ``user32``: ctypes-вызовы не нужны."""
    from map_overlay.infrastructure.win32_input import WindowsInput

    instance = object.__new__(WindowsInput)
    instance._user32 = user32  # type: ignore[attr-defined]
    return instance


def test_combos_are_sent_as_four_key_events() -> None:
    """``Ctrl+A``/``Ctrl+C``/``Ctrl+V`` — по четыре события, ``F`` — два."""
    user32 = _FakeUser32()
    port = _fake_input(user32)
    port.select_all()  # type: ignore[attr-defined]
    port.copy()  # type: ignore[attr-defined]
    port.paste()  # type: ignore[attr-defined]
    port.press_f()  # type: ignore[attr-defined]
    assert user32.click_batches == [
        (0x11, 0x41, 0x41, 0x11),
        (0x11, 0x43, 0x43, 0x11),
        (0x11, 0x56, 0x56, 0x11),
        (0x46, 0x46),
    ]


def test_cursor_position_and_move_report_windows_errors() -> None:
    """Отказ Windows превращается в понятную ошибку, а не в «успех»."""
    from map_overlay.domain.point import Point
    from map_overlay.errors import InputError

    user32 = _FakeUser32()
    port = _fake_input(user32)
    user32.move_ok = False
    with pytest.raises(InputError):
        port.move_cursor(Point(10, 20))  # type: ignore[attr-defined]


def test_modifier_down_checks_every_modifier() -> None:
    """Зажатым считается любой модификатор — по нему шаг отменяется."""
    user32 = _FakeUser32()
    port = _fake_input(user32)
    assert port.modifier_down() is False  # type: ignore[attr-defined]
    user32.modifiers[0x10] = 0x8000
    assert port.modifier_down() is True  # type: ignore[attr-defined]


def test_hook_without_windows_reports_itself_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Вне Windows хук не стартует и честно говорит об этом."""
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    source = WindowsHotkeySource()
    with caplog.at_level("ERROR"):
        source.start_listening(lambda *args: None)
    assert source.failed is True
    assert source.is_available() is False
    assert "только в Windows" in caplog.text
    source.stop_listening()


def test_foreground_check_is_false_without_setup() -> None:
    """Пока Win32-функции не привязаны, «своё окно» не определяется — значит не своё."""
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    assert WindowsHotkeySource()._foreground_is_ours() is False


def test_foreground_check_compares_process_ids() -> None:
    """Своё окно — то, чей процесс совпал с нашим."""
    import ctypes

    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    source = WindowsHotkeySource()
    source._foreground = lambda: 42
    source._own_pid = lambda: 777
    source._owner_of = lambda window, pointer: ctypes.cast(
        pointer, ctypes.POINTER(ctypes.c_ulong)
    ).contents.__setattr__("value", 777)
    assert source._foreground_is_ours() is True
    source._owner_of = lambda window, pointer: ctypes.cast(
        pointer, ctypes.POINTER(ctypes.c_ulong)
    ).contents.__setattr__("value", 1)
    assert source._foreground_is_ours() is False


def test_pass_through_calls_the_next_hook() -> None:
    """Пропуск клавиши возвращает то же решение, что вернул следующий хук."""
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    source = WindowsHotkeySource()
    assert source._pass_through(0, 0x100, 0) == 0
    source._call_next = lambda *args: 5
    assert source._pass_through(0, 0x100, 0) == 5


def test_delivery_reaches_the_callback() -> None:
    """Событие хука доходит до подписчика, а без подписчика просто не падает."""
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    source = WindowsHotkeySource()
    source._deliver(0x68, True, True, False)
    seen: list[tuple[int, bool, bool, bool]] = []
    source._callback = lambda *args: seen.append(args)
    source._deliver(0x68, True, True, False)
    assert seen == [(0x68, True, True, False)]


def test_hook_error_is_passed_through_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ошибка внутри хука не съедает клавиатуру: клавиша проходит, в журнал — один раз."""
    from map_overlay.infrastructure.hotkeys import WindowsHotkeySource

    source = WindowsHotkeySource()
    source._call_next = lambda *args: 0

    def broken(*args: object) -> int:
        raise RuntimeError("сломалось")

    source._decide = broken  # type: ignore[method-assign]
    with caplog.at_level("ERROR"):
        assert source._handle(0, 0x100, 0) == 0
        assert source._handle(0, 0x100, 0) == 0
    assert caplog.text.count("Ошибка в хуке клавиатуры") == 1


def test_alt_tap_needs_the_overlay_window_when_learning_is_on() -> None:
    """При записи привязки активное окно решает, забирать ли клавишу."""
    hook = _HookHarness(learning=True)
    hook.source._foreground = lambda: 1
    hook.source._owner_of = lambda window, pointer: None
    hook.source._own_pid = lambda: 1
    hook.source._owner_of = (
        lambda window, pointer: __import__("ctypes")
        .cast(pointer, __import__("ctypes").POINTER(__import__("ctypes").c_ulong))
        .contents.__setattr__("value", 1)
    )
    # Своё окно: клавиша забирается и уходит в оверлей как новая привязка.
    assert hook.send(0x57, True) == 1
    assert hook.events == [(0x57, True, True)]


def test_learning_outside_the_overlay_lets_keys_through() -> None:
    """В игре клавиатура работает как обычно, даже когда оверлей записывает привязку."""
    hook = _HookHarness(learning=True)
    hook.source._foreground = lambda: 1
    hook.source._own_pid = lambda: 1
    import ctypes

    hook.source._owner_of = lambda window, pointer: ctypes.cast(
        pointer, ctypes.POINTER(ctypes.c_ulong)
    ).contents.__setattr__("value", 999)
    assert hook.send(0x57, True) == 0
    assert hook.events == []


def test_click_moves_the_cursor_and_clicks_twice() -> None:
    """Клик — это наведение курсора и два события мыши: вниз и вверх."""
    from map_overlay.domain.point import Point

    user32 = _FakeUser32()
    port = _fake_input(user32)
    port.click(Point(40, 50))  # type: ignore[attr-defined]
    # Оба события мыши дошли до SendInput: клавишных кодов в пакете нет.
    assert user32.click_batches[0][0] == 0
    assert len(user32.click_batches) == 2


def test_cursor_position_reads_the_native_point() -> None:
    """Позиция курсора переводится в ``Point`` без потерь, ошибка Windows — исключение."""
    from map_overlay.domain.point import Point
    from map_overlay.errors import InputError

    user32 = _FakeUser32()
    port = _fake_input(user32)
    assert port.cursor_position() == Point(300, 120)  # type: ignore[attr-defined]
    user32.cursor_ok = False
    with pytest.raises(InputError):
        port.cursor_position()  # type: ignore[attr-defined]


def test_rejected_input_raises_a_clear_error() -> None:
    """Windows не принял ввод — это ошибка, а не молчаливый пропуск шага."""
    from map_overlay.errors import InputError

    user32 = _FakeUser32()
    user32.send_ok = False
    port = _fake_input(user32)
    with pytest.raises(InputError, match="SendInput"):
        port.press_f()  # type: ignore[attr-defined]
