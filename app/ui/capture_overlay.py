"""PrintScreen-style capture overlay. / Оверлей выбора режима захвата (как PrntScreen).

Frameless always-on-top strip with the three capture modes; the last used mode
is pre-highlighted and confirmed with Enter — like Win+Shift+S / PrtSc muscle
memory. Esc or clicking outside dismisses it.
Бесрамочная всегда-поверх полоса с тремя режимами; последний использованный
режим подсвечен и подтверждается Enter — как у PrtSc / Win+Shift+S.
Esc или клик мимо — отмена.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.i18n import tr

_MODES: tuple[tuple[str, str, str], ...] = (
    ("fullscreen", "🖥", "capture.fullscreen"),
    ("window", "🪟", "capture.active_window"),
    ("region", "▭", "capture.region"),
)


class CaptureOverlay(QWidget):
    """Mode picker shown above everything. / Поверх-всего выбор режима.

    modeChosen(str) — fullscreen | window | region; cancelled() — dismissed.
    """

    modeChosen = Signal(str)
    cancelled = Signal()

    def __init__(self, last_mode: str, parent=None) -> None:
        super().__init__(None)  # independent top-level: never owned by the main window
        self.setObjectName("CaptureOverlay")
        # close() only HIDES: _choose() emits modeChosen right after close() and the
        # window object must still be alive for the signal to reach the main window.
        # Deletion would raise RuntimeError: Signal source has been deleted.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(QSize(640, 216))
        self._current = last_mode if any(m == last_mode for m, _, _ in _MODES) else "fullscreen"
        self._done = False  # set once the picker has been answered or dismissed

        # NOTE: no QGraphicsDropShadowEffect here — the effect paints outside the
        # fixed window rect and breaks layered-window updates on Windows
        # (UpdateLayeredWindowIndirect failed). Keep the card flat instead.

        card = QFrame(self)
        card.setObjectName("CaptureCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(tr("capture.overlay_title"), card)
        title.setObjectName("OverlayTitle")
        head.addWidget(title)
        head.addStretch(1)
        self._last_hint = QLabel(tr("capture.overlay_last", mode=self._mode_label(self._current)), card)
        self._last_hint.setObjectName("OverlayBadge")
        head.addWidget(self._last_hint)
        layout.addLayout(head)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self._buttons: dict[str, QPushButton] = {}
        for index, (mode, glyph, label_key) in enumerate(_MODES, start=1):
            button = QPushButton(card)
            button.setObjectName("ModeButton")
            button.setFixedHeight(96)
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, m=mode: self._choose(m))
            button.setText(f"{glyph}\n{tr(label_key)}\n{index}")
            self._buttons[mode] = button
            buttons.addWidget(button, stretch=1)
        layout.addLayout(buttons)

        hint = QLabel(tr("capture.overlay_hint"), card)
        hint.setObjectName("OverlayHint")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        self._sync_current()
        self._place_on_screen()

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _mode_label(mode: str) -> str:
        return tr(next((key for name, _glyph, key in _MODES if name == mode), "capture.fullscreen"))

    def _sync_current(self) -> None:
        for mode, button in self._buttons.items():
            current = mode == self._current
            button.setChecked(current)
            button.setProperty("current", current)
            button.style().unpolish(button)
            button.style().polish(button)
        self._last_hint.setText(tr("capture.overlay_last", mode=self._mode_label(self._current)))

    # ---------------------------------------------------- keyboard entry
    def handle_command(self, command: str) -> None:
        """One-line keyboard command: escape | enter | 1 | 2 | 3.
        Одно командное слово с клавиатуры: escape | enter | 1 | 2 | 3.

        Called both from keyPressEvent (window has focus) and from the global
        low-level hook in the main window (game holds the foreground window).
        Вызывается и из keyPressEvent (окно в фокусе), и из глобального хука в
        главном окне (фокус у полноэкранной игры).
        """
        if self._done:
            return
        command = (command or "").lower()
        if command == "escape":
            self._done = True
            self.cancelled.emit()
            self.close()
            return
        if command == "enter":
            self._choose(self._current)
            return
        index = {"1": 0, "2": 1, "3": 2}.get(command)
        if index is not None:
            self._choose(_MODES[index][0])

    def _place_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(geometry.center().x() - self.width() // 2,
                  geometry.top() + int(geometry.height() * 0.14))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._place_on_screen()
        self._sync_current()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        try:
            self.grabKeyboard()  # keys reach us even if focus lands elsewhere
        except RuntimeError:    # never let grab failures kill the overlay
            pass
        QTimer.singleShot(0, self.activateWindow)

    def windowDeactivateEvent(self, event) -> None:  # noqa: N802
        # clicking anywhere outside dismisses the picker (Snipping-Tool style)
        if not self._done:
            self._done = True
            self.cancelled.emit()
            self.close()
        super().windowDeactivateEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        command = None
        if key == Qt.Key_Escape:
            command = "escape"
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            command = "enter"
        elif key in (Qt.Key_1, Qt.Key_2, Qt.Key_3):
            command = {Qt.Key_1: "1", Qt.Key_2: "2", Qt.Key_3: "3"}[key]
        if command is not None:
            event.accept()
            self.handle_command(command)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.releaseKeyboard()
        except RuntimeError:
            pass
        super().closeEvent(event)

    def _choose(self, mode: str) -> None:
        if self._done:
            return
        self._done = True
        if mode in ("fullscreen", "window", "region"):
            self._current = mode
            self.close()
            # hide before the grab runs — our own picker must never make it
            # into the screenshot / спрятать до захвата пикселей
            QGuiApplication.processEvents()
            self.modeChosen.emit(mode)
            return
        self.close()
