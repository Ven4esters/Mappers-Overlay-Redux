"""Вкладка «Размеры»: библиотека предметов — название, длина и ширина."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLocale, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QIcon, QPainter, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
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
from map_overlay.errors import AppError, ValidationError
from map_overlay.ui.theme import DANGER_TEXT
from map_overlay.ui.widgets import (
    GRID_SPACING,
    LABEL_COLUMN_WIDTH,
    ROW_SPACING,
    SECTION_GAP,
    Card,
    bullets,
    button,
    hint_label,
    label,
)

SIZE_FIELD_WIDTH = 110
DEFAULT_LENGTH = 2.0
DEFAULT_WIDTH = 1.0
# С чего начинается форма: типичный ящик 2 × 1 м — видно, что куда вписывать.

SUFFIX = " м"
SIZE_COLUMN_WIDTH = 96
# Колонка габаритов в списке: числа «4 × 0.5 м» стоят друг под другом, а не «пляшут».

ADD_HINT: tuple[str, ...] = (
    "Название — ключ: предмет с тем же названием заменяется, регистр не важен.",
    "Размеры задаются в <b>метрах</b>; дробная часть — через точку или запятую.",
)
EDIT_HINT: tuple[str, ...] = (
    "Правка «{name}»: измените название, длину или ширину и нажмите "
    "<b>«Сохранить изменения»</b>.",
    "<b>«Очистить»</b> возвращает форму в режим добавления и не трогает библиотеку.",
)
LIST_HINT: tuple[str, ...] = (
    "<b>«Выбрать»</b> делает предмет текущим: на вкладке «Навигация» его длину, ширину "
    "и половины можно сразу подставить в шаг.",
    "<b>Карандаш</b> — правка записи, <b>корзина</b> — удаление из библиотеки.",
)
ICON_PX = 24
ICON_BUTTON_PX = 30
# Размер рисунка карандаша; на экране он показывается вдвое мельче."


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
        self._rows_layout: QVBoxLayout | None = None
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
        """Форма: подписи в одной колонке, поля начинаются с одного места."""
        card = Card("Предмет")
        form = QGridLayout()
        form.setHorizontalSpacing(ROW_SPACING)
        form.setVerticalSpacing(GRID_SPACING)
        self._name = QLineEdit(self)
        self._name.setMaxLength(MAX_NAME_LEN)
        self._name.setPlaceholderText("Название, например «Ящик»")
        self._length = _size_field(DEFAULT_LENGTH)
        self._width = _size_field(DEFAULT_WIDTH)
        rows = (
            ("Название", self._name, False),
            ("Длина", self._length, True),
            ("Ширина", self._width, True),
        )
        for row, (title, field, with_suffix) in enumerate(rows):
            caption = label(title, widget_role="muted")
            caption.setWordWrap(False)
            caption.setMinimumWidth(LABEL_COLUMN_WIDTH)
            form.addWidget(caption, row, 0)
            if with_suffix:
                # Поле и «м» стоят рядом: единица измерения не уезжает к правому краю.
                host = QWidget(self)
                pair = QHBoxLayout(host)
                pair.setContentsMargins(0, 0, 0, 0)
                pair.setSpacing(6)
                pair.addWidget(field)
                pair.addWidget(label(SUFFIX.strip(), widget_role="muted"))
                pair.addStretch(1)
                form.addWidget(host, row, 1)
            else:
                form.addWidget(field, row, 1)
        form.setColumnStretch(1, 1)
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
        self._clear_button = button("Очистить", tooltip="Очистить поля формы")
        self._clear_button.clicked.connect(self._clear_form)
        buttons_row.addWidget(self._add_button)
        buttons_row.addWidget(self._clear_button)
        buttons_row.addStretch(1)
        card.add_layout(buttons_row)
        self._form_hint = hint_label(*ADD_HINT)
        card.add(self._form_hint)
        return card

    def _build_list(self) -> Card:
        card = Card("Мои предметы")
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
        host = QWidget(self)
        self._rows_layout = QVBoxLayout(host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        card.add(host)
        card.add(hint_label(*LIST_HINT))
        return card

    # --- действия ---------------------------------------------------------

    def _add(self) -> None:
        """Добавить предмет или сохранить правку уже существующего."""
        try:
            item = ObjectSize(
                name=self._name.text(),
                length=_parse_size(self._length, "Длина"),
                width=_parse_size(self._width, "Ширина"),
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
        self._length.setText(_text(DEFAULT_LENGTH))
        self._width.setText(_text(DEFAULT_WIDTH))
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
        self._length.setText(_text(item.length))
        self._width.setText(_text(item.width))
        self._name.setFocus()
        self._name.selectAll()

    def _sync_form_mode(self) -> None:
        """Показать, в каком режиме форма: добавление или правка записи."""
        if self._editing is None:
            self._add_button.setText("Добавить в библиотеку")
            self._add_button.setToolTip("Предмет с таким же названием будет заменён")
            self._form_hint.setText(bullets(*ADD_HINT))
            return
        self._add_button.setText("Сохранить изменения")
        self._add_button.setToolTip(
            "Записать новые название и габариты: порядок в списке и выбранный предмет " "сохранятся"
        )
        self._form_hint.setText(bullets(*(line.format(name=self._editing) for line in EDIT_HINT)))

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
        """Подсказка под формой (для тестов)."""
        return self._form_hint.text()

    def editing_name(self) -> str | None:
        """Название предмета, который сейчас правится (для тестов)."""
        return self._editing

    def press_select(self, name: str) -> None:
        """Сделать предмет текущим (для тестов)."""
        self._activate(name)

    def fill_form(self, name: str, length: str | float, width: str | float) -> None:
        """Заполнить форму (для тестов)."""
        self._name.setText(name)
        self._length.setText(_text(length))
        self._width.setText(_text(width))

    def form_values(self) -> tuple[str, str, str]:
        """Значения формы как введены: название, длина, ширина (для тестов)."""
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
        if self._rows_layout is None:
            return
        self._pencils.clear()
        self._trash_buttons.clear()
        while self._rows_layout.count():
            entry = self._rows_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        for item in items:
            self._rows_layout.addWidget(self._row(item))

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

    def _row(self, item: ObjectSize) -> QWidget:
        host = QWidget(self)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        active = self._library.active is not None and self._library.active.casefold() == item.key
        mark = "✓ " if active else ""
        name = label(f"{mark}{item.name}", widget_role="poseValue")
        name.setWordWrap(True)
        row.addWidget(name, 1)
        # Габариты — отдельной колонкой справа: числа в списке выстраиваются в столбец.
        size = label(f"{item.length:g} × {item.width:g} м", widget_role="poseValue")
        size.setWordWrap(False)
        size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        size.setMinimumWidth(SIZE_COLUMN_WIDTH)
        row.addWidget(size)
        choose = button(
            "Выбрать",
            widget_role="small",
            tooltip="Сделать предмет текущим: его размеры появятся на вкладке «Навигация»",
        )
        choose.setEnabled(not active)
        choose.clicked.connect(lambda _checked=False, name=item.name: self._activate(name))
        pencil = self._icon_button(
            tooltip="Править название и габариты",
            accessible="Править",
            icon=_pencil_icon(self.palette().color(QPalette.ColorRole.Text)),
            name=item.name,
        )
        pencil.clicked.connect(lambda _checked=False, name=item.name: self._begin_edit(name))
        trash = self._icon_button(
            tooltip="Удалить предмет из библиотеки",
            accessible="Удалить",
            icon=_trash_icon(QColor(DANGER_TEXT)),
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
        item = button("", widget_role="small", tooltip=tooltip, danger=danger)
        item.setIcon(icon)
        item.setAccessibleName(accessible)
        item.setProperty("item_name", name)
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


def _trash_icon(color: QColor) -> QIcon:
    """Нарисовать корзину: иконка не зависит от шрифтов и системных наборов значков."""
    size = ICON_PX
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    scale = size / 24.0

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
    return QIcon(pixmap)


def _size_field(value: float) -> QLineEdit:
    """Поле размера: только ввод с клавиатуры, без стрелок «+» и «−»."""
    field = QLineEdit()
    field.setValidator(QDoubleValidator(MIN_SIZE_M, MAX_SIZE_M, SIZE_DECIMALS, field))
    field.setLocale(QLocale.c())
    field.setText(_text(value))
    field.setMaximumWidth(SIZE_FIELD_WIDTH)
    return field


def _text(value: str | float) -> str:
    """Как показывать размер в поле: число с точкой, без хвостовых нулей."""
    if isinstance(value, str):
        return value
    return f"{rounded(value, SIZE_DECIMALS):g}"


def _parse_size(field: QLineEdit, title: str) -> float:
    """Разобрать поле размера: пустое или нечисловое — понятная ошибка.

    Raises:
        ValidationError: если число не читается.
    """
    raw = field.text().replace(",", ".").strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise ValidationError(
            f"{title} должна быть числом, получено «{field.text().strip()}»"
        ) from exc
