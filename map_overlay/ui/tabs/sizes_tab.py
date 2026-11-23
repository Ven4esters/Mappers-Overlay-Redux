"""Вкладка «Размеры»: библиотека предметов — название, длина и ширина."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLocale, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from map_overlay.domain.formatting import rounded
from map_overlay.domain.sizes import (
    MAX_NAME_LEN,
    MAX_SIZE_M,
    MIN_SIZE_M,
    SIZE_DECIMALS,
    ObjectSize,
    SizeLibrary,
)
from map_overlay.errors import AppError, ValidationError
from map_overlay.ui.widgets import Card, button, label

SIZE_FIELD_WIDTH = 110
DEFAULT_LENGTH = 2.0
DEFAULT_WIDTH = 1.0
# С чего начинается форма: типичный ящик 2 × 1 м — видно, что куда вписывать.

SUFFIX = " м"


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
        self._build()
        self._refresh()

    # --- сборка -----------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_form())
        layout.addWidget(self._build_list())
        path = str(self._path) if self._path is not None else "ещё не сохранён"
        layout.addWidget(label(f"Файл размеров: {path}", widget_role="muted"))
        layout.addStretch(1)

    def _build_form(self) -> Card:
        """Форма: название отдельной строкой, под ним длина и ширина."""
        card = Card("Предмет")
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._name = QLineEdit(self)
        self._name.setMaxLength(MAX_NAME_LEN)
        self._name.setPlaceholderText("Название, например «Ящик»")
        name_row.addWidget(label("Название", widget_role="muted"))
        name_row.addWidget(self._name, 1)
        card.add_layout(name_row)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        size_row.addWidget(label("Длина", widget_role="muted"))
        self._length = _size_field(DEFAULT_LENGTH)
        size_row.addWidget(self._length)
        size_row.addWidget(label(SUFFIX.strip(), widget_role="muted"))
        size_row.addSpacing(18)
        size_row.addWidget(label("Ширина", widget_role="muted"))
        self._width = _size_field(DEFAULT_WIDTH)
        size_row.addWidget(self._width)
        size_row.addWidget(label(SUFFIX.strip(), widget_role="muted"))
        size_row.addStretch(1)
        self._add_button = button(
            "Добавить в библиотеку",
            widget_role="primary",
            tooltip="Предмет с таким же названием будет заменён",
        )
        self._add_button.clicked.connect(self._add)
        clear = button("Очистить", tooltip="Очистить поля формы")
        clear.clicked.connect(self._clear_form)
        size_row.addWidget(self._add_button)
        size_row.addWidget(clear)
        card.add_layout(size_row)
        card.add(
            label(
                "Название — ключ: предмет с тем же названием заменяется, регистр не важен. "
                "Размеры задаются в метрах, дробная часть — через точку или запятую.",
                widget_role="muted",
            )
        )
        return card

    def _build_list(self) -> Card:
        card = Card("Мои предметы")
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Поиск по названию")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refresh)
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(label("Поиск", widget_role="muted"))
        search_row.addWidget(self._search, 1)
        card.add_layout(search_row)
        self._empty_label = label("", widget_role="muted")
        card.add(self._empty_label)
        host = QWidget(self)
        self._rows_layout = QVBoxLayout(host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        card.add(host)
        card.add(
            label(
                "«Выбрать» делает предмет текущим: на вкладке «Движение» его длину, ширину "
                "и половины можно сразу подставить в шаг.",
                widget_role="muted",
            )
        )
        return card

    # --- действия ---------------------------------------------------------

    def _add(self) -> None:
        try:
            item = ObjectSize(
                name=self._name.text(),
                length=_parse_size(self._length, "Длина"),
                width=_parse_size(self._width, "Ширина"),
            )
            library = self._library.with_item(item)
        except AppError as exc:
            self.status_message.emit(str(exc))
            return
        self.library_changed.emit(library)

    def _clear_form(self) -> None:
        self._name.clear()
        self._length.setText(_text(DEFAULT_LENGTH))
        self._width.setText(_text(DEFAULT_WIDTH))
        self._name.setFocus()

    def _edit(self, name: str) -> None:
        item = self._library.find(name)
        if item is None:
            return
        self._name.setText(item.name)
        self._length.setText(_text(item.length))
        self._width.setText(_text(item.width))

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

    def press_delete(self, name: str) -> None:
        """Удалить предмет по названию (для тестов и окна)."""
        self._delete(name)

    def press_edit(self, name: str) -> None:
        """Перенести предмет в форму (для тестов)."""
        self._edit(name)

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
        """Предметы, подходящие под запрос поиска (без учёта регистра)."""
        query = self._search.text().strip().casefold()
        if not query:
            return list(self._library.items)
        return [item for item in self._library.items if query in item.name.casefold()]

    def _refresh(self, _text: str = "") -> None:
        items = self._visible_items()
        self._empty_label.setText(self._hint(len(items)))
        if self._rows_layout is None:
            return
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
        if visible == total:
            return f"Предметов: {total}"
        return f"Найдено: {visible} из {total}"

    def _row(self, item: ObjectSize) -> QWidget:
        host = QWidget(self)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        active = self._library.active is not None and self._library.active.casefold() == item.key
        mark = "✓ " if active else ""
        row.addWidget(label(f"{mark}{item.text()}", widget_role="poseValue"), 1)
        choose = button(
            "Выбрать",
            widget_role="small",
            tooltip="Сделать предмет текущим: его размеры появятся на вкладке «Движение»",
        )
        choose.setEnabled(not active)
        choose.clicked.connect(lambda _checked=False, name=item.name: self._activate(name))
        edit = button("В форму", widget_role="small", tooltip="Перенести значения в поля выше")
        edit.clicked.connect(lambda _checked=False, name=item.name: self._edit(name))
        remove = button("Удалить", widget_role="small", tooltip="Убрать предмет из библиотеки")
        remove.clicked.connect(lambda _checked=False, name=item.name: self._delete(name))
        row.addWidget(choose)
        row.addWidget(edit)
        row.addWidget(remove)
        return host


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
