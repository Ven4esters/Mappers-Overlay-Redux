"""Вкладка «Размеры»: библиотека предметов — название, длина и ширина."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPixmap,
    QPolygonF,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from map_overlay.domain.formatting import rounded
from map_overlay.domain.search import NameSearch
from map_overlay.domain.sizes import (
    MAX_NAME_LEN,
    MAX_SIZE_M,
    MIN_SIZE_M,
    SIZE_DECIMALS,
    ObjectSize,
    SizeLibrary,
)
from map_overlay.errors import AppError
from map_overlay.ui.theme import DANGER_TEXT
from map_overlay.ui.widgets import (
    GRID_SPACING,
    LABEL_COLUMN_WIDTH,
    ROW_SPACING,
    SECTION_GAP,
    Card,
    DecimalSpinBox,
    button,
    label,
)

SIZE_FIELD_WIDTH = 140
# Минимальная ширина поля размера: в узком окне ниже не опускается, в широком растягивается.
DEFAULT_LENGTH = 2.0
DEFAULT_WIDTH = 1.0
# С чего начинается форма: типичный ящик 2 × 1 м — видно, что куда вписывать.

SUFFIX = " м"
ROW_MARGIN_X = 8
ROW_MARGIN_Y = 6
ROW_MIN_HEIGHT = 44
# Минимальная высота строки: название и габариты в две строки плюс поля.
# Поля строки списка: подсветка выбранной строки видна по краям, текст не липнет к рамке.

ADD_HINT = (
    "Название — ключ: предмет с тем же названием заменяется, регистр не важен.\n"
    "Например: «Ящик», 2 × 1 м — длина и ширина в метрах, дробная часть через точку\n"
    "или запятую."
)
EDIT_HINT = (
    "Правка «{name}»: измените название, длину или ширину и нажмите «Сохранить изменения».\n"
    "«Очистить» возвращает форму в режим добавления и не трогает библиотеку."
)
LIST_HINT = (
    "Поиск находит по любому слову названия и по номеру из диапазона: «стена 01» найдёт\n"
    "«Стена 01-39», а уточнение запроса сужает выдачу.\n"
    "«Выбрать» делает предмет текущим: на вкладке «Навигация» его длину, ширину и половины\n"
    "можно сразу подставить в шаг. Карандаш — правка записи, корзина — удаление.\n"
    "Шаги отменяются в окне: Ctrl+Z — вернуть предмет, Ctrl+Y — повторить шаг (до 20)."
)
ICON_TEXT = "#c3ccdb"
# Карандаш светлый: палитра окна тёмная только через QSS, поэтому цвет задан явно.
ICON_PX = 24
ICON_DRAW_PX = 20
# Значок показывается 20 px в кнопке 32 px: карандаш и корзина читаются одинаково.
ICON_BUTTON_PX = 32
# Поле рисунка: значки рисуются в сетке 24 px, а на экране занимают ICON_DRAW_PX.


class SizesTab(QWidget):
    """Добавление, правка и удаление предметов с габаритами."""

    library_changed = Signal(object)
    status_message = Signal(str)

    def __init__(
        self,
        *,
        library: SizeLibrary,
        path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._path = path
        self._search_engine = NameSearch()
        self._editing: str | None = None
        self._pencils: dict[str, QPushButton] = {}
        self._trash_buttons: dict[str, QPushButton] = {}
        self._build()
        self._refresh()

    # --- сборка -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(SECTION_GAP)
        layout.addWidget(self._build_form())
        layout.addWidget(self._build_list())
        path = str(self._path) if self._path is not None else "ещё не сохранён"
        layout.addWidget(label(f"Файл размеров: {path}", widget_role="muted"))
        layout.addStretch(1)

    def _build_form(self) -> Card:
        """Форма: название во всю ширину, длина и ширина — в одном ряду."""
        card = Card("Предмет", hint=ADD_HINT)
        self._form_card = card
        form = QGridLayout()
        form.setHorizontalSpacing(ROW_SPACING)
        form.setVerticalSpacing(GRID_SPACING)
        self._name = QLineEdit(self)
        self._name.setMaxLength(MAX_NAME_LEN)
        # Коротко: пример («Ящик») живёт в справке под ⓘ и не обрезается в узком окне.
        self._name.setPlaceholderText("Введите название…")
        self._length = _size_spin(DEFAULT_LENGTH)
        self._width = _size_spin(DEFAULT_WIDTH)
        name_caption = label("Название", widget_role="muted")
        name_caption.setMinimumWidth(LABEL_COLUMN_WIDTH)
        name_caption.setWordWrap(False)
        form.addWidget(name_caption, 0, 0)
        form.addWidget(self._name, 0, 1, 1, 3)
        # Длина и ширина стоят рядом: две колонки заполняют карточку, а не оставляют
        # пустое поле справа от узких полей.
        for column, (title, field) in enumerate((("Длина", self._length), ("Ширина", self._width))):
            caption = label(title, widget_role="muted")
            caption.setWordWrap(False)
            caption.setMinimumWidth(LABEL_COLUMN_WIDTH)
            form.addWidget(caption, 1, column * 2)
            form.addWidget(field, 1, column * 2 + 1)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        card.add_layout(form)

        # Кнопки — отдельной строкой: в одну строку с полями и подписями они не влезали
        # в узкое окно, и правый край формы уходил за границу карточки.
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(ROW_SPACING)
        self._add_button = button(
            "Добавить в библиотеку",
            widget_role="primary",
            tooltip="Предмет с таким же названием будет заменён",
        )
        self._add_button.clicked.connect(self._add)
        self._clear_button = button(
            "Очистить",
            widget_role="clear",
            tooltip="Очистить поля формы",
        )
        self._clear_button.clicked.connect(self._clear_form)
        buttons_row.addWidget(self._add_button)
        buttons_row.addWidget(self._clear_button)
        buttons_row.addStretch(1)
        card.add_layout(buttons_row)
        return card

    def _build_list(self) -> Card:
        card = Card("Мои предметы", hint=LIST_HINT)
        self._list_card = card
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Поиск: слова названия или номер из диапазона")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refresh)
        search_grid = QGridLayout()
        search_grid.setHorizontalSpacing(ROW_SPACING)
        search_grid.setVerticalSpacing(4)
        caption = label("Поиск", widget_role="muted")
        caption.setWordWrap(False)
        caption.setMinimumWidth(LABEL_COLUMN_WIDTH)
        search_grid.addWidget(caption, 0, 0)
        search_grid.addWidget(self._search, 0, 1)
        # Счётчик найденного — под полем поиска: он не отнимает у поля ширину.
        self._empty_label = label("", widget_role="hint")
        search_grid.addWidget(self._empty_label, 1, 1)
        search_grid.setColumnStretch(1, 1)
        card.add_layout(search_grid)

        self._list = QListWidget(self)
        self._list.setObjectName("sizesList")
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setSpacing(2)
        self._list.setUniformItemSizes(False)
        card.add(self._list)
        return card

    # --- действия ---------------------------------------------------------

    def _add(self) -> None:
        """Добавить предмет или сохранить правку уже существующего."""
        try:
            item = ObjectSize(
                name=self._name.text(),
                length=self._length.value(),
                width=self._width.value(),
            )
            if self._editing is None:
                library = self._library.with_item(item)
            else:
                library = self._library.replace(self._editing, item)
        except AppError as exc:
            self.status_message.emit(str(exc))
            return
        self._editing = None
        self._sync_form_mode()
        self.library_changed.emit(library)

    def _clear_form(self) -> None:
        self._name.clear()
        self._length.setValue(DEFAULT_LENGTH)
        self._width.setValue(DEFAULT_WIDTH)
        self._editing = None
        self._sync_form_mode()
        self._name.setFocus()

    def _begin_edit(self, name: str) -> None:
        """Взять предмет в правку: название и габариты в поля, кнопка — «Сохранить»."""
        item = self._library.find(name)
        if item is None:
            return
        self._editing = item.name
        self._sync_form_mode()
        self._name.setText(item.name)
        self._length.setValue(item.length)
        self._width.setValue(item.width)
        self._name.setFocus()
        self._name.selectAll()

    def _sync_form_mode(self) -> None:
        """Показать, в каком режиме форма: добавление или правка записи."""
        if self._editing is None:
            self._add_button.setText("Добавить в библиотеку")
            self._add_button.setToolTip("Предмет с таким же названием будет заменён")
            self._form_card.set_hint(ADD_HINT)
            return
        self._add_button.setText("Сохранить изменения")
        self._add_button.setToolTip(
            "Записать новые название и габариты: порядок в списке и выбранный предмет сохранятся"
        )
        self._form_card.set_hint(EDIT_HINT.format(name=self._editing))

    def _delete(self, name: str) -> None:
        item = self._library.find(name)
        if item is None:
            return
        self.library_changed.emit(self._library.without(item.name))

    def _activate(self, name: str) -> None:
        item = self._library.find(name)
        if item is None:
            return
        self.library_changed.emit(self._library.select(item.name))

    # --- состояние --------------------------------------------------------

    def set_library(self, library: SizeLibrary) -> None:
        """Показать новую библиотеку (после сохранения или удаления)."""
        self._library = library
        self._search_engine.reset()
        if self._editing is not None and library.find(self._editing) is None:
            self._editing = None
            self._sync_form_mode()
        self._refresh()

    def library(self) -> SizeLibrary:
        """Текущая библиотека (для тестов и окна)."""
        return self._library

    def row_names(self) -> list[str]:
        """Названия видимых строк списка (для тестов)."""
        return [item.name for item in self._visible_items()]

    def list_hint(self) -> str:
        """Текст подсказки над списком (для тестов)."""
        return self._empty_label.text()

    def search_text(self) -> str:
        """Текущий запрос поиска (для тестов)."""
        return self._search.text()

    def press_search(self, query: str) -> None:
        """Ввести запрос поиска (для тестов)."""
        self._search.setText(query)

    def press_add(self) -> None:
        """Нажать «Добавить в библиотеку» (для тестов)."""
        self._add_button.click()

    def press_clear(self) -> None:
        """Нажать «Очистить» — выйти из правки и обнулить поля (для тестов)."""
        self._clear_button.click()

    def trash(self, name: str) -> QPushButton | None:
        """Кнопка-корзина строки (для тестов)."""
        return self._trash_buttons.get(name)

    def press_delete(self, name: str) -> None:
        """Нажать корзину в строке предмета (для тестов и окна)."""
        item = self._trash_buttons.get(name)
        if item is not None:
            item.click()
            return
        self._delete(name)

    def press_pencil(self, name: str) -> None:
        """Нажать карандаш в строке предмета — взять запись в правку (для тестов)."""
        item = self._pencils.get(name)
        if item is not None:
            item.click()

    def pencil(self, name: str) -> QPushButton | None:
        """Кнопка-карандаш строки (для тестов)."""
        return self._pencils.get(name)

    def add_button_text(self) -> str:
        """Надпись на главной кнопке формы (для тестов)."""
        return self._add_button.text()

    def form_hint(self) -> str:
        """Справка формы — то, что показывает значок ⓘ (для тестов)."""
        return self._form_card.hint()

    def help_texts(self) -> tuple[str, str]:
        """Справка карточек «Предмет» и «Мои предметы» (для тестов)."""
        return self._form_card.hint(), self._list_card.hint()

    def editing_name(self) -> str | None:
        """Название предмета, который сейчас правится (для тестов)."""
        return self._editing

    def press_select(self, name: str) -> None:
        """Сделать предмет текущим (для тестов)."""
        self._activate(name)

    def fill_form(self, name: str, length: str | float, width: str | float) -> None:
        """Заполнить форму (для тестов): числа можно писать строкой, с запятой."""
        self._name.setText(name)
        _set_size(self._length, length)
        _set_size(self._width, width)

    def form_values(self) -> tuple[str, str, str]:
        """Значения формы как их видит пользователь: название и поля с « м» (для тестов)."""
        return self._name.text(), self._length.text(), self._width.text()

    def _visible_items(self) -> list[ObjectSize]:
        """Предметы, подходящие под запрос, — от точных совпадений к частичным.

        Ищется по мере набора: «Mar» находит «Стена March», а каждое следующее слово
        сужает выдачу. Правила — в :class:`map_overlay.domain.search.NameSearch`.
        """
        names = [item.name for item in self._library.items]
        by_name = {item.name: item for item in self._library.items}
        return [by_name[name] for name in self._search_engine.match(names, self._search.text())]

    def _refresh(self, _text: str = "") -> None:
        items = self._visible_items()
        self._empty_label.setText(self._hint(len(items)))
        self._pencils.clear()
        self._trash_buttons.clear()
        self._list.clear()
        for item in items:
            entry = QListWidgetItem(self._list)
            entry.setData(Qt.ItemDataRole.UserRole, item.name)
            row = self._row(item)
            self._list.addItem(entry)
            self._list.setItemWidget(entry, row)
            if self._is_active(item):
                self._list.setCurrentItem(entry)
        self._resize_rows()

    def _resize_rows(self) -> None:
        """Высота строки — по её ширине: перенесённое название не наезжает на соседнюю."""
        width = max(self._list.viewport().width(), 200)
        for index in range(self._list.count()):
            entry = self._list.item(index)
            # Виджет есть у каждой строки: строки создаются вместе с записями списка.
            row = self._list.itemWidget(entry)
            # Высоту считаем заново по ширине, а не берём sizeHint: у переносящего
            # названия sizeHint зависит от текущей ширины и застревает на старом значении.
            height = max(row.heightForWidth(width), ROW_MIN_HEIGHT)
            if entry.sizeHint().height() != height:
                entry.setSizeHint(QSize(0, height))
        self._fit_list()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - имя из Qt
        """При изменении ширины пересчитать высоты строк списка."""
        super().resizeEvent(event)
        if hasattr(self, "_list"):
            self._resize_rows()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - имя из Qt
        """Первая раскладка: список получает настоящую ширину только после показа."""
        super().showEvent(event)
        QTimer.singleShot(0, self._resize_rows)

    def _fit_list(self) -> None:
        """Список занимает ровно свою высоту: прокрутка у вкладки, а не внутри списка.

        Высота считается по ``sizeHint`` записей, а не по ``sizeHintForRow``: список
        кэширует высоту строк и отдаёт старую, пока не пересчитает раскладку.
        """
        gap = self._list.spacing()
        height = 2 * self._list.frameWidth()
        for index in range(self._list.count()):
            height += self._list.item(index).sizeHint().height() + gap
        self._list.setFixedHeight(max(height, ROW_MIN_HEIGHT))

    def _hint(self, visible: int) -> str:
        """Подсказка над списком: пусто, ничего не найдено или сколько показано."""
        if not self._library.items:
            return (
                "Пока пусто: впишите название, длину и ширину — и нажмите «Добавить в библиотеку»."
            )
        if not visible:
            return f"Ничего не найдено по запросу «{self._search.text().strip()}»"
        total = len(self._library.items)
        engine = self._search_engine
        note = f" · номер совпал {engine.note}" if engine.loose else ""
        if visible == total and not note:
            return f"Предметов: {total}"
        return f"Найдено: {visible} из {total}{note}"

    def _is_active(self, item: ObjectSize) -> bool:
        """Этот предмет — текущий (из него берётся шаг)."""
        active = self._library.active
        return active is not None and active.casefold() == item.key

    def _row(self, item: ObjectSize) -> QWidget:
        """Строка списка: название с габаритами слева, действия — в правом краю."""
        host = QWidget(self)
        row = QHBoxLayout(host)
        row.setContentsMargins(ROW_MARGIN_X, ROW_MARGIN_Y, ROW_MARGIN_X, ROW_MARGIN_Y)
        row.setSpacing(10)
        # Название и габариты — один блок: размеры не «болтаются» посередине строки,
        # а стоят сразу под своим названием.
        text = QVBoxLayout()
        text.setSpacing(0)
        text.setContentsMargins(0, 0, 0, 0)
        name = label(item.name, widget_role="rowName")
        name.setWordWrap(True)
        # Клик по тексту выбирает строку: метка не перехватывает мышь у списка.
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        size = label(f"{item.length:g} × {item.width:g} м", widget_role="rowSize")
        size.setWordWrap(False)
        size.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text.addWidget(name)
        text.addWidget(size)
        text.addStretch(1)
        # Блок «название + размеры» стоит по центру строки, а не прижат к её верхнему краю.
        row.addLayout(text, 1)
        row.setAlignment(text, Qt.AlignmentFlag.AlignVCenter)
        choose = button(
            "Выбрать",
            widget_role="ghost",
            tooltip="Сделать предмет текущим: его размеры появятся на вкладке «Навигация»",
        )
        choose.setEnabled(not self._is_active(item))
        choose.clicked.connect(lambda _checked=False, name=item.name: self._activate(name))
        pencil = self._icon_button(
            tooltip="Править название и габариты",
            accessible="Править",
            icon=_pencil_icon(QColor(ICON_TEXT)),
            name=item.name,
        )
        pencil.clicked.connect(lambda _checked=False, name=item.name: self._begin_edit(name))
        trash = self._icon_button(
            tooltip="Удалить предмет из библиотеки",
            accessible="Удалить",
            icon=_trash_icon(QColor(DANGER_TEXT), hover=QColor("#ffffff")),
            name=item.name,
            danger=True,
        )
        trash.clicked.connect(lambda _checked=False, name=item.name: self._delete(name))
        row.addWidget(choose)
        row.addWidget(pencil)
        row.addWidget(trash)
        self._pencils[item.name] = pencil
        self._trash_buttons[item.name] = trash
        return host

    def _icon_button(
        self,
        *,
        tooltip: str,
        accessible: str,
        icon: QIcon,
        name: str,
        danger: bool = False,
    ) -> QPushButton:
        """Кнопка-значок размером с иконку: подпись заменена рисунком и подсказкой."""
        item = button("", widget_role="icon", tooltip=tooltip, danger=danger)
        item.setIcon(icon)
        item.setAccessibleName(accessible)
        item.setProperty("item_name", name)
        item.setIconSize(QSize(ICON_DRAW_PX, ICON_DRAW_PX))
        item.setFixedSize(ICON_BUTTON_PX, ICON_BUTTON_PX)
        return item


def _pencil_icon(color: QColor) -> QIcon:
    """Нарисовать карандаш: иконка не зависит от шрифтов и значков системы."""
    size = ICON_PX
    # Рисуем в логических точках: pixmap с devicePixelRatio 2 сам удвоит разрешение для
    # экранов HiDPI. Дополнительный масштаб здесь не нужен — иначе рисунок обрежется.
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    scale = size / 24.0
    body = QPolygonF(
        [
            QPointF(3.0 * scale, 17.25 * scale),
            QPointF(3.0 * scale, 21.0 * scale),
            QPointF(6.75 * scale, 21.0 * scale),
            QPointF(17.81 * scale, 9.94 * scale),
            QPointF(14.06 * scale, 6.19 * scale),
        ]
    )
    cap = QPolygonF(
        [
            QPointF(20.71 * scale, 7.04 * scale),
            QPointF(16.96 * scale, 3.29 * scale),
            QPointF(15.13 * scale, 5.13 * scale),
            QPointF(18.88 * scale, 8.88 * scale),
        ]
    )
    painter.drawPolygon(body)
    painter.drawPolygon(cap)
    painter.end()
    return QIcon(pixmap)


def _trash_icon(color: QColor, *, hover: QColor | None = None) -> QIcon:
    """Нарисовать корзину: иконка не зависит от шрифтов и системных наборов значков.

    Корзина уже карандаша, поэтому рисуется крупнее — иначе она выглядит мелкой.
    ``hover`` — цвет рисунка под курсором (на красной подложке он белый).
    """
    size = ICON_PX
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    # 24 → 22: силуэт корзины подрастает до высоты карандаша.
    scale = size / 22.0

    def polygon(points: list[tuple[float, float]]) -> QPolygonF:
        return QPolygonF([QPointF(x * scale, y * scale) for x, y in points])

    painter.drawPolygon(polygon([(5.0, 5.0), (19.0, 5.0), (19.0, 7.5), (5.0, 7.5)]))
    painter.drawPolygon(polygon([(9.0, 2.5), (15.0, 2.5), (15.0, 5.0), (9.0, 5.0)]))
    painter.drawPolygon(polygon([(6.5, 8.5), (17.5, 8.5), (16.5, 21.0), (7.5, 21.0)]))
    # Рёбра корзины вырезаем: сплошной силуэт в 16 px читается хуже.
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.fillRect(
        QRectF(10.0 * scale, 10.5 * scale, 1.2 * scale, 8.0 * scale), Qt.GlobalColor.transparent
    )
    painter.fillRect(
        QRectF(13.0 * scale, 10.5 * scale, 1.2 * scale, 8.0 * scale), Qt.GlobalColor.transparent
    )
    painter.end()
    icon = QIcon(pixmap)
    if hover is not None:
        # Активное состояние — это наведение: Qt берёт его для кнопки под курсором.
        ring = QPixmap(size * 2, size * 2)
        ring.setDevicePixelRatio(2.0)
        ring.fill(Qt.GlobalColor.transparent)
        painter = QPainter(ring)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(hover)
        painter.drawPolygon(polygon([(5.0, 5.0), (19.0, 5.0), (19.0, 7.5), (5.0, 7.5)]))
        painter.drawPolygon(polygon([(9.0, 2.5), (15.0, 2.5), (15.0, 5.0), (9.0, 5.0)]))
        painter.drawPolygon(polygon([(6.5, 8.5), (17.5, 8.5), (16.5, 21.0), (7.5, 21.0)]))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(
            QRectF(10.0 * scale, 10.5 * scale, 1.2 * scale, 8.0 * scale),
            Qt.GlobalColor.transparent,
        )
        painter.fillRect(
            QRectF(13.0 * scale, 10.5 * scale, 1.2 * scale, 8.0 * scale),
            Qt.GlobalColor.transparent,
        )
        painter.end()
        icon.addPixmap(ring, QIcon.Mode.Active)
    return icon


class SizeSpin(DecimalSpinBox):
    """Поле размера с единицей внутри: «2.5 м».

    Единица измерения живёт в тексте поля (``setSuffix``), а не отдельной подписью:
    сетка не разъезжается, и глаз не прыгает между числом и «м».
    Запятая принимается наравне с точкой — так размеры пишут в игре, а локаль C
    не даёт системе подменить разделитель в поле.
    """

    def __init__(self, value: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDecimals(SIZE_DECIMALS)
        self.setRange(MIN_SIZE_M, MAX_SIZE_M)
        self.setSuffix(SUFFIX)
        self.setSingleStep(0.1)
        # Стрелки «+» и «−» не нужны: размер вписывают с клавиатуры.
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(SIZE_FIELD_WIDTH)
        self.setValue(value)

    def valueFromText(self, text: str) -> float:  # noqa: N802 - имя из Qt
        """Прочитать «2,5 м» и «2.5 м» одинаково (единица в тексте не мешает)."""
        return super().valueFromText(text.replace(SUFFIX, ""))

    def textFromValue(self, value: float) -> str:  # noqa: N802 - имя из Qt
        """Показать число без хвостовых нулей: «2 м», а не «2.000 м»."""
        return f"{rounded(value, SIZE_DECIMALS):g}"


def _size_spin(value: float) -> SizeSpin:
    """Поле размера формы (QDoubleSpinBox с единицей внутри)."""
    return SizeSpin(value)


def _set_size(field: SizeSpin, value: str | float) -> None:
    """Заполнить поле размера из теста или кода: строка может быть с запятой."""
    if isinstance(value, str):
        field.lineEdit().setText(f"{value}{SUFFIX}")
        field.interpretText()
        return
    field.setValue(value)
