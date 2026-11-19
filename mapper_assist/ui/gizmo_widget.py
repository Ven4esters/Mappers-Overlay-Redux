from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..math3d import rotate_2d_gta


class GizmoWidget(QWidget):
    """
    Визуальный 2D мини-компас ориентации объекта сверху (Top-Down GTA V):
      - Пунктирные голубые оси — базовый угол комнаты (Якорь);
      - Зелёная стрелка — локальный «Вперёд» (+Y);
      - Оранжевая стрелка — локальное «Вправо» (+X).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rz: float = 0.0
        self._anchor_rz: float = 0.0
        self._use_anchor_mode: bool = False
        self.setMinimumSize(112, 112)
        self.setMaximumSize(132, 132)
        self.setToolTip(
            "Вид сверху (GTA V):\n"
            "• Зелёная стрелка — Вперёд\n"
            "• Оранжевая стрелка — Вправо\n"
            "• Пунктир — Якорь комнаты"
        )

    def set_angles(self, rz: float, anchor_rz: float, use_anchor_mode: bool = False) -> None:
        self._rz = float(rz)
        self._anchor_rz = float(anchor_rz)
        self._use_anchor_mode = bool(use_anchor_mode)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        radius = min(w, h) / 2.0 - 12.0

        # Фон круга
        painter.setPen(QPen(QColor("#2c3b4e"), 1.3))
        painter.setBrush(QColor("#0d1218"))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        # Мировые засечки С/Ю/З/В
        world_pen = QPen(QColor("#243140"), 1.0)
        painter.setPen(world_pen)
        painter.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        painter.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))

        # Сетка базового угла комнаты (Якоря)
        anchor_pen = QPen(QColor("#38bdf8" if self._use_anchor_mode else "#1e4e68"), 1.2, Qt.PenStyle.DashLine)
        painter.setPen(anchor_pen)
        ax_f, ay_f = rotate_2d_gta(0.0, radius * 0.92, self._anchor_rz)
        ax_r, ay_r = rotate_2d_gta(radius * 0.92, 0.0, self._anchor_rz)
        painter.drawLine(QPointF(cx - ax_f, cy + ay_f), QPointF(cx + ax_f, cy - ay_f))
        painter.drawLine(QPointF(cx - ax_r, cy + ay_r), QPointF(cx + ax_r, cy - ay_r))

        active_angle = self._anchor_rz if self._use_anchor_mode else self._rz
        arr_len = radius * 0.78

        # Стрелка Вправо (+X) — оранжевая
        rx_dx, rx_dy = rotate_2d_gta(arr_len, 0.0, active_angle)
        self._draw_arrow(
            painter,
            QPointF(cx, cy),
            QPointF(cx + rx_dx, cy - rx_dy),
            QColor("#f59e0b"),
        )

        # Стрелка Вперёд (+Y) — зелёная
        fw_dx, fw_dy = rotate_2d_gta(0.0, arr_len, active_angle)
        self._draw_arrow(
            painter,
            QPointF(cx, cy),
            QPointF(cx + fw_dx, cy - fw_dy),
            QColor("#22c55e"),
        )

        # Центральная точка
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e2e8f0"))
        painter.drawEllipse(QPointF(cx, cy), 3.0, 3.0)

        # Подпись Севера (N) и текущего угла
        font = QFont("Segoe UI", 8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#64748b"))
        painter.drawText(int(cx - 4), 10, "N")

        painter.setPen(QColor("#cbd5e1"))
        angle_txt = f"{self._rz:+.1f}°"
        painter.drawText(6, int(h - 3), angle_txt)

    @staticmethod
    def _draw_arrow(painter: QPainter, start: QPointF, end: QPointF, color: QColor) -> None:
        pen = QPen(color, 2.2)
        painter.setPen(pen)
        painter.drawLine(start, end)

        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return

        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head_len = 7.0
        head_w = 4.0

        p1 = end
        p2 = QPointF(end.x() - ux * head_len + px * head_w, end.y() - uy * head_len + py * head_w)
        p3 = QPointF(end.x() - ux * head_len - px * head_w, end.y() - uy * head_len - py * head_w)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([p1, p2, p3]))
