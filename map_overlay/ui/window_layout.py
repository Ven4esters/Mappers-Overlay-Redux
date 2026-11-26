"""Раскладка окна: размеры по содержимому и мини-версия.

Окно не сжимается ниже того, что требует содержимое вкладок, а мини-версия прячет
вкладки, название и версию, возвращая прежний размер при обратном переключении.
Всё это — геометрия, поэтому методы собраны здесь, отдельно от сценариев панели."""

from __future__ import annotations

import logging

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QScrollArea,
)

from map_overlay.ui.window_base import WindowBase

WINDOW_WIDTH = 640
WINDOW_HEIGHT = 820
MINI_WIDTH = 380
MINI_HEIGHT = 430
# Мини-версия: крестовина, шаг и выбор предмета без прокрутки и переключения вкладок.
MIN_WINDOW_HEIGHT = 320
# Ниже этого окно не опускается даже при ограничении по экрану: останется одна шапка.
SCREEN_HEIGHT_MARGIN = 48
# Запас от края экрана: заголовок окна, панель задач и место, чтобы окно можно было тащить.


logger = logging.getLogger(__name__)


class WindowLayoutMixin(WindowBase):
    """Часть окна: см. описание модуля, состояние — в ``WindowBase``."""

    def toggle_mini(self) -> None:
        """Переключить обычный вид и мини-версию."""
        self.set_mini(not self._mini)

    def set_mini(self, enabled: bool) -> None:
        """Свернуть окно до мини-версии (крестовина и шаг) или вернуть полный вид.

        В мини-версии прячутся вкладки и подписи: остаётся только то, чем двигают
        предмет. Обратное переключение возвращает прежний размер и прежнюю вкладку.
        """
        if enabled == self._mini:
            return
        self._mini = enabled
        if enabled:
            self._normal_size = (self.width(), self.height())
            self._normal_tab = self._tabs.currentIndex()
            self._tabs.setCurrentIndex(0)
            self._tabs.tabBar().setVisible(False)
            self._calibration_label.setVisible(False)
            # В мини-версии название и версия не нужны: они занимали половину шапки и
            # не давали окну сузиться до 380 пикселей.
            self._title_label.setVisible(False)
            self._version_label.setVisible(False)
            self._mini_button.setText("Обычный")
            self._mini_button.setToolTip("Вернуть полное окно: вкладки, калибровка, настройки")
            self.movement.set_compact(True)
            self._fit_layout()
            self._resize_to_fit(MINI_WIDTH, MINI_HEIGHT)
        else:
            self._tabs.tabBar().setVisible(True)
            self._calibration_label.setVisible(True)
            self._title_label.setVisible(True)
            self._version_label.setVisible(True)
            self._mini_button.setText("Мини")
            self._mini_button.setToolTip("Свернуть окно до крестовины и шага")
            self.movement.set_compact(False)
            self._fit_layout()
            width, height = self._normal_size or (WINDOW_WIDTH, WINDOW_HEIGHT)
            self._fit_layout()
            self._resize_to_fit(width, height)
            if 0 <= self._normal_tab < self._tabs.count():
                self._tabs.setCurrentIndex(self._normal_tab)

    def needed_width(self) -> int:
        """Наименьшая ширина, при которой содержимое вкладок не обрезается.

        Горизонтальной прокрутки у вкладок нет: всё, что шире окна, просто исчезает.
        Ширина содержимого зависит от системного шрифта — на Windows (Segoe UI) и при
        увеличенном шрифте она больше эталонных 640 пикселей, и вкладка обрезалась.
        Поэтому окно не сжимается ниже фактической потребности, а не «до константы».
        """
        indexes = [self._tabs.currentIndex()] if self._mini else range(self._tabs.count())
        needed = 0
        for index in indexes:
            area = self._tabs.widget(index)
            content = area.widget() if isinstance(area, QScrollArea) else None
            if content is not None:
                needed = max(needed, content.minimumSizeHint().width())
        if not needed:
            return 0
        current = self._tabs.currentWidget()
        frame = 0
        if isinstance(current, QScrollArea):
            # Рамка, отступы и полоса прокрутки вокруг содержимого вкладки.
            frame = max(0, self.width() - current.viewport().width())
        return needed + frame

    def needed_height(self) -> int:
        """Наименьшая высота, при которой содержимое вкладок не обрезается.

        Вертикальной прокрутки у вкладок нет: всё, что выше окна, просто исчезает. Высота
        содержимого растёт вместе с системным шрифтом (Windows при 125–200 %), поэтому
        окно дорастает по факту, а не по эталонным 820 пикселям.
        """
        indexes = [self._tabs.currentIndex()] if self._mini else range(self._tabs.count())
        needed = 0
        for index in indexes:
            area = self._tabs.widget(index)
            content = area.widget() if isinstance(area, QScrollArea) else None
            if content is not None:
                needed = max(needed, content.minimumSizeHint().height())
        if not needed:
            return 0
        current = self._tabs.currentWidget()
        chrome = 0
        if isinstance(current, QScrollArea):
            # Шапка, строка вкладок, строка состояния и отступы вокруг содержимого.
            chrome = max(0, self.height() - current.height())
        return needed + chrome

    def _height_limit(self) -> int:
        """Сколько высоты даёт экран: дальше окно не растёт, иначе низ уедет за край."""
        # ``QWidget.screen()`` в offscreen-платформе роняет процесс, поэтому спрашиваем
        # приложение: окно всё равно открывается на основном мониторе.
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().height() - SCREEN_HEIGHT_MARGIN
        return max(MIN_WINDOW_HEIGHT, available)

    def _grow_to_fit_height(self) -> None:
        """Дорастить окно до содержимого вкладки, не выходя за экран.

        Меряется только показанное окно: до первого показа раскладка ещё не посчитана,
        и «минимальная высота» вкладки — временное число в разы больше настоящего.
        """
        if not self.isVisible():
            return
        needed = min(self.needed_height(), self._height_limit())
        if needed > self.height():
            self.resize(self.width(), needed)

    def fit_to_content(self) -> None:
        """Дорастить окно до содержимого текущей вкладки.

        Нужно там, где окно показывают целиком, а не листают: скриншоты для README и
        проверки раскладки. Предел экрана здесь не действует — картинка живёт без экрана.
        В обычной работе рост делает ``_resize_to_fit``.
        """
        needed_width = self.needed_width()
        needed_height = self.needed_height()
        width = max(self.width(), needed_width)
        height = max(self.height(), needed_height)
        if width != self.width() or height != self.height():
            self.resize(width, height)

    def _resize_to_fit(self, width: int, height: int) -> None:
        """Поставить заданный размер, но не уже, чем требует содержимое.

        Мерить приходится после ``resize``: до него раскладка ещё держит минимум прежнего
        вида, и мини-версия оставалась шириной с полное окно.
        """
        self.setMinimumWidth(width)
        self.resize(width, height)
        # Скрытые в мини-версии поля сообщают о себе запросом раскладки, а не сразу:
        # без этой обработки минимум ширины считался бы по полному виду.
        QCoreApplication.sendPostedEvents(None, int(QEvent.Type.LayoutRequest.value))
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        needed = self.needed_width()
        if needed > width:
            self.setMinimumWidth(needed)
            self.resize(needed, height)
        self._grow_to_fit_height()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - имя из Qt
        """Первый показ: подогнать ширину и высоту под фактический шрифт системы."""
        super().showEvent(event)
        needed = self.needed_width()
        if needed > self.width():
            self.setMinimumWidth(needed)
            self.resize(needed, self.height())
        # Рост по высоте — после показа: менять размер внутри showEvent нельзя, Qt
        # на этом падает при финализации окна в тестах.
        QTimer.singleShot(0, self._grow_to_fit_height)

    def _fit_layout(self) -> None:
        """Пересчитать минимальный размер окна после скрытия части вкладки.

        Qt кэширует минимальный размер от раскладки: без пересчёта ``resize`` в мини-версии
        упирался в ширину полного окна, и мини-окно оставалось большим.
        """
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        # Сбросить минимальный размер, который Qt оставил от прежнего вида: он и не давал
        # окну стать уже. Раскладка оставит свой минимум сама на следующем проходе.
        self.setMinimumSize(0, 0)
        self.resize(self.minimumSizeHint())

    def press_mini(self) -> None:
        """Нажать «Мини»/«Обычный» (для тестов)."""
        self._mini_button.click()

    def is_mini(self) -> bool:
        """Включена ли мини-версия (для тестов)."""
        return self._mini

    def mini_button_text(self) -> str:
        """Надпись на переключателе мини-версии (для тестов)."""
        return self._mini_button.text()

    def tab_bar_visible(self) -> bool:
        """Видна ли строка вкладок (для тестов)."""
        return self._tabs.tabBar().isVisible()

    def tabs_index(self) -> int:
        """Номер текущей вкладки (для тестов)."""
        return self._tabs.currentIndex()

    def select_tab(self, index: int) -> None:
        """Переключить вкладку по номеру (для тестов)."""
        self._tabs.setCurrentIndex(index)

    def tab_fits(self, index: int) -> bool:
        """Помещается ли содержимое вкладки в окно по ширине (для тестов).

        Горизонтальная прокрутка выключена, поэтому всё, что шире окна, просто обрезается.
        Проверка ловит именно это: скрытые поля ввода и лишние кнопки раздували вкладку.
        """
        area = self._tabs.widget(index)
        if not isinstance(area, QScrollArea):
            return True
        content = area.widget()
        return content is None or content.width() <= area.viewport().width()

    def tab_fits_height(self, index: int) -> bool:
        """Помещается ли содержимое вкладки в окно по высоте (для тестов).

        Вертикальной прокрутки у вкладок нет, поэтому всё, что выше окна, обрезается:
        на 200 % нижний переключатель уезжал под сгиб.
        """
        area = self._tabs.widget(index)
        if not isinstance(area, QScrollArea):
            return True
        content = area.widget()
        return content is None or content.height() <= area.viewport().height()

    def tab_titles(self) -> list[str]:
        """Названия вкладок по порядку."""
        return [self._tabs.tabText(index) for index in range(self._tabs.count())]
