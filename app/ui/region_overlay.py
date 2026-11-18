"""Translucent full-desktop overlay for region picking. / Оверлей выбора области.

Covers the whole virtual desktop, paints a dimmed backdrop, shows an accent
rubber-band rectangle; ``regionSelected`` carries a global *logical* QRect
(scale it by devicePixelRatio before handing it to ``app.capture``).
Покрывает весь виртуальный десктоп, рисует затемнение и рамку;
``regionSelected`` отдаёт глобальный ЛОГИЧЕСКИЙ QRect (умножьте на DPR).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.theme import COLORS

MIN_SELECTION = 8  # logical pixels — below this we treat it as a click, not a selection


def virtual_geometry() -> QRect:
    from PySide6.QtGui import QGuiApplication

    screens = QGuiApplication.screens()
    if not screens:
        return QRect(0, 0, 1920, 1080)
    geometry = screens[0].geometry()
    for screen in screens[1:]:
        geometry = geometry.united(screen.geometry())
    return geometry


class RegionOverlay(QWidget):
    regionSelected = Signal(QRect)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(virtual_geometry())
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self.showFullScreen()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(4, 8, 20, 170))
        if self._origin is not None and self._current is not None:
            selection = self._selection_rect()
            painter.fillRect(selection, QColor(79, 125, 255, 36))
            pen = QPen(QColor(COLORS["accent_hi"]))
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(selection)
        painter.end()

    def _selection_rect(self) -> QRect:
        assert self._origin is not None and self._current is not None
        origin = self._origin - self.geometry().topLeft()
        current = self._current - self.geometry().topLeft()
        return QRect(origin, current).normalized()

    # -------------------------------------------------------------- events
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._current = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or self._origin is None:
            return
        self._current = event.globalPosition().toPoint()
        rect = QRect(self._origin, self._current).normalized()
        self.hide()
        if rect.width() >= MIN_SELECTION and rect.height() >= MIN_SELECTION:
            self.regionSelected.emit(rect)
        else:
            self.cancelled.emit()
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
        else:
            super().keyPressEvent(event)
