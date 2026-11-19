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
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
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
        super().__init__(parent)
        self.setObjectName("CaptureOverlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(QSize(640, 216))
        self._current = last_mode if any(m == last_mode for m, _, _ in _MODES) else "fullscreen"
        self._done = False  # set once the picker has been answered or dismissed

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 170))
        shadow.setOffset(0, 10)
        self.setGraphicsEffect(shadow)

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
        if key == Qt.Key_Escape:
            event.accept()
            if not self._done:
                self._done = True
                self.cancelled.emit()
            self.close()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            event.accept()
            self._choose(self._current)
            return
        index = {Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2}.get(key)
        if index is not None:
            event.accept()
            self._choose(_MODES[index][0])
            return
        super().keyPressEvent(event)

    def _choose(self, mode: str) -> None:
        if self._done:
            return
        self._done = True
        if mode in ("fullscreen", "window", "region"):
            self._current = mode
            self.modeChosen.emit(mode)
        self.close()
