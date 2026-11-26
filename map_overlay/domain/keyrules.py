"""Правила перехвата клавиш: что забирать у игры, а что пропускать.

Решения принимаются здесь, а не в хуке: хук — тонкая обёртка над ``SetWindowsHookEx``,
и на Linux его не проверить. Всё, что можно решить без Windows, живёт в этом файле и
покрыто тестами.

Три вещи решаются тут:

* :func:`blocks_key` — забирать ли нажатие или отпускание у системы;
* :func:`is_modifier` — модификатор ли это (``Ctrl``, ``Shift``, ``Alt``);
* :func:`alt_tap` — было ли нажатие одиночным нажатием ``Alt`` (им включается высота).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

from map_overlay.domain.keynames import MODIFIER_KEYS, VK_MENU, generic_vk


def is_modifier(vk: int) -> bool:
    """Модификатор ли это (``Shift``, ``Ctrl``, ``Alt`` и их версии со стороной)."""
    return generic_vk(vk) in MODIFIER_KEYS


@dataclass(frozen=True, slots=True)
class KeyBinding:
    """Что сейчас назначено: обычные клавиши и клавиши только с ``Ctrl``."""

    bound: Collection[int] = field(default_factory=frozenset)
    bound_ctrl: Collection[int] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class KeyState:
    """Состояние системы и оверлея в момент нажатия."""

    ctrl_down: bool = False
    learning: bool = False
    overlay_active: bool = False
    swallowed: Collection[int] = field(default_factory=frozenset)


def blocks_key(*, vk: int, is_down: bool, binding: KeyBinding, state: KeyState) -> bool:
    """Забирать ли нажатие у системы.

    Правила:

    * в обычном режиме перехватываются только назначенные клавиши;
    * клавиши отмены и повтора (``bound_ctrl``) забираются только с зажатым Ctrl и
      только когда окно оверлея не активно: без Ctrl это обычные Z и Y, а при
      открытом окне их обрабатывает оно само (в полях ввода Ctrl+Z правит текст);
    * при записи новой привязки — любые клавиши, но только пока окно оверлея активно:
      в игре клавиатура должна работать всегда;
    * отпускание клавиши забирается лишь тогда, когда было забрано её нажатие —
      иначе игра получила бы «зажатую» клавишу.
    """
    if not is_down:
        return vk in state.swallowed
    if state.learning:
        # Модификаторы при записи привязки только мешают: Ctrl+Z должен дать «Z»,
        # а не привязку к Ctrl.
        return state.overlay_active and not is_modifier(vk)
    if vk in binding.bound_ctrl:
        return state.ctrl_down and not state.overlay_active
    return vk in binding.bound


def needs_foreground(vk: int, binding: KeyBinding, *, ctrl_down: bool, learning: bool) -> bool:
    """Нужно ли спрашивать у системы активное окно перед решением.

    Спрашивать стоит только там, где ответ меняет решение: при записи привязки и для
    клавиш отмены с ``Ctrl``. Иначе — два вызова Win32 на каждую клавишу зря.
    """
    return learning or (ctrl_down and vk in binding.bound_ctrl)


@dataclass(slots=True)
class AltTracker:
    """Следит за одиночным нажатием ``Alt``.

    ``Alt`` не забирается у игры: он проходит как обычно. Переключателем режима высоты
    считается только одиночное нажатие, а комбинация (``Alt+Tab``, ``Alt+F4``,
    ``Alt+Num 8``) — нет, иначе режим менялся бы во время обычной работы.
    """

    down: bool = False
    alone: bool = False

    def observe(self, vk: int, is_down: bool, *, injected: bool = False) -> bool:
        """Заметить клавишу; вернуть ``True``, если это было одиночное нажатие Alt.

        Клавиши, которые оверлей посылает сам (``Ctrl+A``, ``Ctrl+V``), не считаются
        нажатием человека: иначе во время шага любое нажатие Alt выглядело бы
        комбинацией, и режим не переключался бы.
        """
        if injected:
            return False
        if vk == VK_MENU:
            if is_down:
                if not self.down:
                    self.down = True
                    self.alone = True
                return False
            self.down = False
            alone = self.alone
            self.alone = False
            return alone
        if self.down:
            self.alone = False
        return False
