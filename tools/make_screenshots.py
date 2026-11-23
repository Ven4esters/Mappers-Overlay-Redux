"""Скриншоты и схема для README: собираются из настоящего интерфейса, а не рисуются руками.

Зачем так. Скриншот, нарисованный в редакторе, устаревает молча: в прошлый раз README
показывал версию 1.5.0 с вкладкой «Движение», которой уже нет. Здесь окно собирается тем
же кодом, что и у пользователя, а значения подставляются демонстрационные — поэтому
переименованная вкладка или новая кнопка сразу видна на картинке.

Запуск::

    python -m tools.make_screenshots

Файлы пишутся в ``docs/``:

* ``screenshot-navigation.png`` — вкладка «Навигация» со считанной позой;
* ``screenshot-sizes.png`` — вкладка «Размеры» с библиотекой;
* ``screenshot-calibration.png`` — вкладка «Калибровка»;
* ``screenshot-settings.png`` — вкладка «Настройки»;
* ``screenshot-mini.png`` — мини-версия окна;
* ``diagonal-rx.png`` — как меняется диагональ при повороте ``RX``.

Схема диагоналей считается настоящей функцией сдвига, поэтому картинка не может
разойтись с формулами в коде.
"""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parent.parent
DOCS: Final = ROOT / "docs"

# Qt без экрана: окно рисуется в память. Переменную надо выставить до импорта PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))

from map_overlay.config import Settings  # noqa: E402
from map_overlay.context import AppContext  # noqa: E402
from map_overlay.domain.directions import Direction  # noqa: E402
from map_overlay.domain.fields import Field  # noqa: E402
from map_overlay.domain.formatting import format_value  # noqa: E402
from map_overlay.domain.movement import shifted  # noqa: E402
from map_overlay.domain.point import Point  # noqa: E402
from map_overlay.domain.pose import Pose  # noqa: E402
from map_overlay.domain.sizes import ObjectSize, SizeLibrary  # noqa: E402
from map_overlay.ui import theme  # noqa: E402
from map_overlay.ui.appicon import icon as app_icon  # noqa: E402
from map_overlay.ui.window import (  # noqa: E402
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    MainWindow,
)
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402 - импорт после настройки Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DEMO_POSE: Final = Pose(x=-1848.763, y=409.366, z=125.002, rx=37.0, ry=0.0, rz=0.0)
DEMO_CALIBRATION: Final[dict[Field, Point]] = {
    Field.X: Point(1180, 210),
    Field.Y: Point(1350, 210),
    Field.Z: Point(1520, 210),
    Field.RX: Point(1180, 268),
    Field.RY: Point(1350, 268),
    Field.RZ: Point(1520, 268),
}
DEMO_EMPTY_POINT: Final = Point(1120, 420)
DEMO_SIZES: Final[tuple[ObjectSize, ...]] = (
    ObjectSize(name="Стена March, TID, Hood, Soup, New, 01-39", length=4.0, width=0.5),
    ObjectSize(name="Длинная стена 01-10", length=8.0, width=0.6),
    ObjectSize(name="Стена с дверным проёмом", length=4.0, width=0.6),
    ObjectSize(name="Ящик March", length=1.2, width=0.8),
    ObjectSize(name="Дверь", length=1.0, width=0.2),
)
DEMO_ACTIVE: Final = "Стена March, TID, Hood, Soup, New, 01-39"
SCALE: Final = 2
"""Скриншоты вдвое крупнее логических пикселей: на экранах с масштабом они не мылят."""


class DemoPanel:
    """Панель LSP в памяти: отдаёт демонстрационную позу и принимает запись."""

    def __init__(self, pose: Pose) -> None:
        self._values = {field: format_value(pose.value(field), 3) for field in Field}

    def read_field(self, field: Field) -> str:
        """Прочитать поле: текст, как его показала бы панель."""
        return self._values[field]

    def write_field(self, field: Field, text: str) -> None:
        """Записать поле."""
        self._values[field] = text

    def missing_points(self) -> tuple[Field, ...]:
        """Полей без точки калибровки нет: всё настроено."""
        return ()

    def has_confirmation_point(self) -> bool:
        """Точка для клика перед ``F`` задана."""
        return True

    def confirm(self) -> None:
        """Клик в пустое место и ``F``: на скриншоте не нажимается."""
        return

    def cancel(self) -> None:
        """Отменять нечего."""
        return

    def cancelled(self) -> bool:
        """Обмен не отменялся."""
        return False

    def reset_cancel(self) -> None:
        """Снимать нечего."""
        return


class DemoCursor:
    """Курсор с неподвижной позицией."""

    def cursor_position(self) -> Point:
        """Позиция курсора: для калибровки на скриншоте не нужна."""
        return Point(900, 500)

    def move_cursor(self, point: Point) -> None:
        """Переместить курсор — на скриншоте не нужно."""
        del point
        return


class DemoSettings:
    """Настройки в памяти."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load(self) -> Settings:
        """Отдать демонстрационные настройки."""
        return self.settings

    def save(self, settings: Settings) -> None:
        """Запомнить настройки (вкладка «Настройки» их сохраняет)."""
        self.settings = settings


class DemoSizes:
    """Библиотека размеров в памяти."""

    def __init__(self, library: SizeLibrary) -> None:
        self.library = library

    def load(self) -> SizeLibrary:
        """Отдать демонстрационную библиотеку."""
        return self.library

    def save(self, library: SizeLibrary) -> None:
        """Запомнить библиотеку."""
        self.library = library


class DemoHotkeys:
    """Перехват клавиш, который ничего не перехватывает: на скриншоте клавиши не жмут."""

    def start_listening(self, on_key: Callable[[int, bool, bool], None]) -> None:
        """Запомнить обработчик и сразу замолчать."""
        del on_key
        return

    def stop_listening(self) -> None:
        """Слушать нечего."""
        return

    def configure(self, *, bound_keys: Collection[int], learning: bool) -> None:
        """Принять список клавиш: он на скриншот не влияет."""
        del bound_keys, learning
        return

    def set_enabled(self, enabled: bool) -> None:
        """Перехват включается и выключается без последствий."""
        del enabled
        return

    def freeze(self, enabled: bool) -> None:
        """Заморозка на скриншоте не нужна."""
        del enabled
        return

    def num_lock_enabled(self) -> bool | None:
        """NumLock включён: иначе окно показало бы предупреждение вместо рабочего вида."""
        return True

    def key_down(self, vk: int) -> bool:
        """Ни одна клавиша не зажата."""
        del vk
        return False

    def is_available(self) -> bool:
        """Перехват доступен."""
        return True


def _demo_settings() -> Settings:
    return Settings(
        calibration=DEMO_CALIBRATION,
        empty_point=DEMO_EMPTY_POINT,
        default_step=0.5,
        verify_writes=True,
    )


def _demo_library() -> SizeLibrary:
    library = SizeLibrary()
    for item in DEMO_SIZES:
        library = library.with_item(item)
    return library.select(DEMO_ACTIVE)


def _build_window(app: QApplication) -> MainWindow:
    """Собрать окно с демонстрационными данными и одной считанной позой."""
    settings = _demo_settings()
    panel = DemoPanel(DEMO_POSE)
    context = AppContext(
        store=DemoSettings(settings),
        cursor=DemoCursor(),
        panel_factory=lambda _settings: panel,
        hotkeys=DemoHotkeys(),
        config_path=Path("config") / "settings.json",
        size_store=DemoSizes(_demo_library()),
        sizes_path=Path("config") / "sizes.json",
    )
    window = MainWindow(context, synchronous_tasks=True)
    window.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
    window.show()
    app.processEvents()
    window.movement.press_capture()
    window.movement.press_size_search("Стена")
    app.processEvents()
    return window


def _grab(window: MainWindow, app: QApplication, path: Path) -> None:
    """Сохранить снимок окна (вместе со строкой состояния)."""
    # Раскладке нужно два прохода: после скрытия строк окно меняет размер, и только
    # второй проход расставляет виджеты по новым местам.
    app.processEvents()
    app.processEvents()
    window.repaint()
    pixmap = window.grab()
    if not pixmap.save(str(path), "PNG"):
        raise SystemExit(f"не удалось сохранить {path}")
    print(f"{path.name}: {pixmap.width()}×{pixmap.height()}, {path.stat().st_size} байт")


def _save_shots(app: QApplication) -> None:
    window = _build_window(app)
    tabs = {
        "screenshot-navigation.png": 0,
        "screenshot-sizes.png": 1,
        "screenshot-calibration.png": 2,
        "screenshot-settings.png": 3,
    }
    for name, index in tabs.items():
        window.select_tab(index)
        _grab(window, app, DOCS / name)
    window.select_tab(0)
    window.set_mini(True)
    _grab(window, app, DOCS / "screenshot-mini.png")
    window.close()


PANEL_W: Final = 292
PANEL_H: Final = 300
GAP: Final = 18
DIAGRAM_RX: Final = (0.0, 37.0, 60.0, 90.0)
DIAGRAM_STEP: Final = 0.5


def _diagonal_points(rx: float) -> tuple[float, float]:
    """Сдвиг ``Num 9`` при заданном ``RX``: возвращает ``ΔY`` и ``ΔZ`` из настоящего кода."""
    pose = Pose(x=0.0, y=0.0, z=0.0, rx=rx, ry=0.0, rz=0.0)
    after = shifted(pose, Direction.FORWARD_RIGHT, DIAGRAM_STEP)
    return after.y - pose.y, after.z - pose.z


def _draw_panel(painter: QPainter, left: float, top: float, rx: float) -> None:
    """Одна карточка схемы: оси, стрелка диагонали и подписи."""
    painter.setPen(QPen(QColor(theme.BORDER), 1))
    painter.setBrush(QColor(theme.SURFACE))
    painter.drawRoundedRect(QRectF(left, top, PANEL_W, PANEL_H), 10, 10)

    center = QPointF(left + PANEL_W / 2, top + PANEL_H / 2)
    dash = QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine)
    painter.setPen(dash)
    painter.drawLine(QPointF(left + 24, center.y()), QPointF(left + PANEL_W - 24, center.y()))
    painter.drawLine(QPointF(center.x(), top + 24), QPointF(center.x(), top + PANEL_H - 24))

    dy, dz = _diagonal_points(rx)
    scale = 330.0
    end = QPointF(center.x() - dy * scale, center.y() - dz * scale)
    painter.setPen(QPen(QColor(theme.SUCCESS), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(center, end)
    painter.setBrush(QColor(theme.SUCCESS))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(end, 4, 4)
    painter.drawEllipse(center, 3, 3)

    screen_angle = math.degrees(math.atan2(dz, -dy))
    painter.setPen(QColor(theme.TEXT))
    title = QFont(painter.font())
    title.setBold(True)
    title.setPointSizeF(11.5)
    painter.setFont(title)
    painter.drawText(
        QRectF(left, top + PANEL_H + 8, PANEL_W, 22),
        Qt.AlignmentFlag.AlignCenter,
        f"RX = {rx:g}°",
    )
    painter.setFont(QFont(painter.font().family(), 9))
    painter.setPen(QColor(theme.MUTED))
    painter.drawText(
        QRectF(left, top + PANEL_H + 30, PANEL_W, 20),
        Qt.AlignmentFlag.AlignCenter,
        f"ΔY {dy:+.3f} · ΔZ {dz:+.3f}",
    )
    painter.drawText(
        QRectF(left, top + PANEL_H + 50, PANEL_W, 20),
        Qt.AlignmentFlag.AlignCenter,
        f"угол на экране {screen_angle:.0f}°",
    )


def _save_diagram() -> None:
    """Нарисовать схему: как поворот ``RX`` поворачивает диагональ в плоскости ``Y/Z``."""
    width = len(DIAGRAM_RX) * PANEL_W + (len(DIAGRAM_RX) + 1) * GAP
    height = 140 + PANEL_H + 80
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(theme.BACKGROUND))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    heading = QFont(painter.font().family(), 15)
    heading.setBold(True)
    painter.setFont(heading)
    painter.setPen(QColor(theme.TEXT))
    painter.drawText(
        QRectF(GAP, 18, width - 2 * GAP, 30),
        Qt.AlignmentFlag.AlignLeft,
        "Диагональ Num 9: поворот в плоскости Y/Z, X не меняется",
    )
    caption = QFont(painter.font().family(), 10)
    painter.setFont(caption)
    painter.setPen(QColor(theme.MUTED))
    painter.drawText(
        QRectF(GAP, 46, width - 2 * GAP, 24),
        Qt.AlignmentFlag.AlignLeft,
        "Шаг 0.5 м, RY = 0. Вправо на экране — Y в минус, вверх — Z в плюс: "
        "ΔY = ay·(шаг/√2)·sin RX, ΔZ = ax·(шаг/√2)·cos RX",
    )

    for index, rx in enumerate(DIAGRAM_RX):
        _draw_panel(painter, GAP + index * (PANEL_W + GAP), 96, rx)

    painter.setFont(QFont(painter.font().family(), 10))
    painter.setPen(QColor(theme.MUTED))
    painter.drawText(
        QRectF(GAP, 96 + PANEL_H + 82, width - 2 * GAP, 40),
        Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
        "Поворот вокруг X оставляет X неизменным, а Y и Z крутит в их плоскости: угол на экране "
        "= 90° − RX, длина сдвига в этой плоскости постоянна (шаг/√2). Первая карточка — отдельный "
        "случай «без наклона»: 45° и полная длина шага. Пара Num 7/3 считается обратной "
        "тригонометрией: у неё sin RX уходит в Z.",
    )
    painter.end()

    path = DOCS / "diagonal-rx.png"
    # QImage.save ждёт формат строкой, хотя заглушки типов объявляют bytes.
    if not image.save(str(path), "PNG"):  # type: ignore[call-overload]
        raise SystemExit(f"не удалось сохранить {path}")
    print(f"{path.name}: {image.width()}×{image.height()}, {path.stat().st_size} байт")


def main() -> int:
    """Собрать окно и сохранить все картинки для README."""
    os.environ["QT_SCALE_FACTOR"] = str(SCALE)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    DOCS.mkdir(parents=True, exist_ok=True)
    app = QApplication([sys.argv[0]])
    app.setStyleSheet(theme.APP_QSS)
    app.setWindowIcon(app_icon())
    _save_shots(app)
    _save_diagram()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
