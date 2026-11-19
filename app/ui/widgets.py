"""Small reusable UI pieces. / Переиспользуемые UI-примитивы."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from app.i18n import tr
from app.hotkey_parse import DEFAULT_HOTKEY, is_reserved, normalize_hotkey

# Qt.Key → canonical token (values never hard-coded — always enum members)
_KEY_TOKENS: dict = {}
for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _KEY_TOKENS[getattr(Qt.Key, f"Key_{_letter}")] = _letter
for _digit in "0123456789":
    _KEY_TOKENS[getattr(Qt.Key, f"Key_{_digit}")] = _digit
for _n in range(1, 25):
    _KEY_TOKENS[getattr(Qt.Key, f"Key_F{_n}")] = f"F{_n}"
_KEY_TOKENS.update({
    Qt.Key.Key_Print: "Print", Qt.Key.Key_ScrollLock: "ScrollLock",
    Qt.Key.Key_Pause: "Pause", Qt.Key.Key_NumLock: "NumLock",
    Qt.Key.Key_Space: "Space", Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Escape: "Escape",
    Qt.Key.Key_Backspace: "Backspace", Qt.Key.Key_Return: "Return", Qt.Key.Key_Enter: "Return",
    Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Delete: "Delete",
    Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End",
    Qt.Key.Key_PageUp: "PageUp", Qt.Key.Key_PageDown: "PageDown",
    Qt.Key.Key_Left: "Left", Qt.Key.Key_Up: "Up", Qt.Key.Key_Right: "Right", Qt.Key.Key_Down: "Down",
})
_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta}
_MOD_PARTS = ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
              (Qt.KeyboardModifier.ShiftModifier, "Shift"),
              (Qt.KeyboardModifier.AltModifier, "Alt"),
              (Qt.KeyboardModifier.MetaModifier, "Meta"))


class HotkeyRecorder(QPushButton):
    """Button that records a hotkey combo. / Кнопка записи сочетания клавиш.

    Click to arm; the next non-modifier keypress becomes the new combo.
    Escape cancels arming. Emits ``captureFinished(combo)`` (canonical) on
    success, ``rejected`` when the combo is reserved or unsupported.
    Клик — запись; следующая не-модификаторная клавиша становится хоткеем.
    Escape отменяет. ``captureFinished(combo)`` — успех, ``rejected`` — отказ.
    """

    captureFinished = Signal(str)
    rejected = Signal()
    armedChanged = Signal(bool)  # True while waiting for a key (for pausing global hotkeys)

    def __init__(self, hotkey: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HotkeyRecorder")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._hotkey = normalize_hotkey(hotkey) or DEFAULT_HOTKEY
        self._armed = False
        self._render()

    def current(self) -> str:
        return self._hotkey

    def set_hotkey(self, combo: str) -> None:
        self._hotkey = normalize_hotkey(combo) or DEFAULT_HOTKEY
        self._render()

    def _render(self) -> None:
        self.setText(self._hotkey)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._arm()
        super().mousePressEvent(event)

    def _arm(self) -> None:
        if self._armed:
            return
        self._armed = True
        self.setText(tr("settings.hotkey_press"))
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.armedChanged.emit(True)

    def _disarm(self) -> None:
        if not self._armed:
            return
        self._armed = False
        self._render()
        self.armedChanged.emit(False)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._disarm()
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self._armed:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._disarm()
            event.accept()
            return
        if key in _MODIFIER_KEYS:
            event.accept()  # wait for the base key
            return
        base = _KEY_TOKENS.get(key)
        event.accept()
        if base is None:
            self._disarm()
            self.rejected.emit()
            return
        modifiers = event.modifiers()
        parts = [name for flag, name in _MOD_PARTS if modifiers & flag]
        parts.append(base)
        combo = normalize_hotkey("+".join(parts))
        if combo is None or is_reserved(combo):
            self._disarm()
            self.rejected.emit()
            return
        self._hotkey = combo
        self._disarm()
        self.captureFinished.emit(combo)



class SegmentedControl(QWidget):
    """Mutually-exclusive row of checkable buttons (replaces tiny combo boxes).
    Взаимоисключающий ряд кнопок (замена маленьких выпадающих списков).

    ``currentChanged`` carries the selected option id.
    """

    currentChanged = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None) -> None:
        """options: [(id, label), ...] left-to-right. / Варианты слева направо."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for option_id, label in options:
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setObjectName("Segmented")
            button.setFocusPolicy(Qt.StrongFocus)
            button.clicked.connect(lambda _checked=False, key=option_id: self._on_clicked(key))
            self._group.addButton(button)
            self._buttons[option_id] = button
            layout.addWidget(button, stretch=1)

    def _on_clicked(self, option_id: str) -> None:
        self.currentChanged.emit(option_id)

    def set_current(self, option_id: str) -> None:
        button = self._buttons.get(option_id)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def current(self) -> str:
        for option_id, button in self._buttons.items():
            if button.isChecked():
                return option_id
        return next(iter(self._buttons), "")
