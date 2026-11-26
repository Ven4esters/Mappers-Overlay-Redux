"""Иконка приложения: рисуется кодом, поэтому не зависит от картинок и шрифтов.

Один рисунок обслуживает все места, где иконка нужна:

* окно и панель задач — :func:`icon`;
* `.exe` — `map_overlay/data/app.ico`, собранный из того же рисунка
  (`python -m tools.make_icons`);
* документация — `docs/app-icon.png` из того же прогона.

Рисунок: тёмный скруглённый квадрат (цвета темы приложения) и белая крестовина
из четырёх стрелок с синей сердцевиной — то, чем оверлей и занимается: двигает
предмет по восьми направлениям.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
    QPolygonF,
)

CANVAS: Final = 256
# Рисуем в системе 256 × 256 и масштабируем: так все размеры выглядят одинаково.

SIZES: Final[tuple[int, ...]] = (16, 24, 32, 48, 64, 128, 256)
# Размеры, которые попадут в .ico: от значка в списке окон до крупного ярлыка.

BACKGROUND_TOP: Final = "#1d2739"
BACKGROUND_BOTTOM: Final = "#0e131c"
BORDER: Final = "#26324a"
ARROW: Final = "#e6ebf5"
ACCENT: Final = "#3b82f6"
ACCENT_LIGHT: Final = "#93c5fd"

CORNER_RADIUS: Final = 56.0
ARROW_POINTS: Final[tuple[tuple[float, float], ...]] = (
    (128.0, 36.0),
    (158.0, 84.0),
    (98.0, 84.0),
)
# Основание стрелки оставлено с зазором до сердцевины: иначе четыре стрелки сливаются
# в сплошной ромб, и значок в 16 px читается как белое пятно.
# Стрелка вверх: вершина и два угла основания. Остальные три получаются поворотом.


def pixmap(size: int, *, ratio: float = 1.0) -> QPixmap:
    """Нарисовать иконку заданного размера (``ratio`` — запас под HiDPI)."""
    scaled = max(1, round(size * ratio))
    canvas = QPixmap(scaled, scaled)
    # devicePixelRatio уже учитывает запас под HiDPI: рисуем в логических точках, иначе
    # рисунок увеличится дважды и обрежется по краю pixmap.
    canvas.setDevicePixelRatio(ratio)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    logical = scaled / ratio
    painter.scale(logical / CANVAS, logical / CANVAS)
    _draw_background(painter)
    _draw_pad(painter)
    painter.end()
    return canvas


def icon() -> QIcon:
    """Иконка со всеми размерами: Qt сам выберет подходящий для окна и панели задач."""
    result = QIcon()
    for size in SIZES:
        result.addPixmap(pixmap(size, ratio=2.0))
    return result


def _draw_background(painter: QPainter) -> None:
    """Скруглённый квадрат с градиентом темы и тонкой рамкой."""
    body = QRectF(6.0, 6.0, CANVAS - 12.0, CANVAS - 12.0)
    gradient = QLinearGradient(body.topLeft(), body.bottomRight())
    gradient.setColorAt(0.0, QColor(BACKGROUND_TOP))
    gradient.setColorAt(1.0, QColor(BACKGROUND_BOTTOM))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(body, CORNER_RADIUS, CORNER_RADIUS)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    border = painter.pen()
    border.setColor(QColor(BORDER))
    border.setWidthF(4.0)
    painter.setPen(border)
    painter.drawRoundedRect(body, CORNER_RADIUS, CORNER_RADIUS)


def _draw_pad(painter: QPainter) -> None:
    """Четыре стрелки вокруг сердцевины: крестовина направлений."""
    # Каждая стрелка — та же фигура, повёрнутая на 90° вокруг центра.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ARROW))
    for angle in (0.0, 90.0, 180.0, 270.0):
        painter.save()
        painter.translate(CANVAS / 2, CANVAS / 2)
        painter.rotate(angle)
        painter.translate(-CANVAS / 2, -CANVAS / 2)
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in ARROW_POINTS]))
        painter.restore()
    # Сердцевина: ромб акцентного цвета с бликом.
    diamond = QPolygonF(
        [
            QPointF(128.0, 102.0),
            QPointF(154.0, 128.0),
            QPointF(128.0, 154.0),
            QPointF(102.0, 128.0),
        ]
    )
    painter.setBrush(QColor(ACCENT))
    painter.drawPolygon(diamond)
    painter.setBrush(QColor(ACCENT_LIGHT))
    painter.drawEllipse(QPointF(128.0, 128.0), 8.0, 8.0)


def png_bytes(size: int) -> bytes:
    """PNG одного размера в памяти: нужен для сборки .ico и документации."""
    image: QImage = pixmap(size).toImage()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    # PySide6 6.8 принимает формат только строкой, хотя заглушка типов ждёт bytes.
    image.save(buffer, "PNG")  # type: ignore[call-overload]
    buffer.close()
    return buffer.data().data()
