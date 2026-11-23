"""Вкладка «Размеры»: библиотека предметов — название, длина и ширина."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from map_overlay.domain.sizes import (
    MAX_NAME_LEN,
    MAX_SIZE_M,
    MIN_SIZE_M,
    SIZE_DECIMALS,
    ObjectSize,
    SizeLibrary,
)
from map_overlay.errors import AppError
from map_overlay.ui.widgets import Card, button, label

SIZE_SPIN_WIDTH = 110
DEFAULT_LENGTH = 2.0
DEFAULT_WIDTH = 1.0
# С чего начинается форма: типичный ящик 2 × 1 м — видно, что куда вписывать.


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
        card = Card("Предмет")
        row = QHBoxLayout()
        row.setSpacing(8)
        self._name = QLineEdit(self)
        self._name.setMaxLength(MAX_NAME_LEN)
        self._name.setPlaceholderText("Название, например «Ящик»")
        self._length = _size_spin(DEFAULT_LENGTH)
        self._width = _size_spin(DEFAULT_WIDTH)
        row.addWidget(label("Название", widget_role="muted"))
        row.addWidget(self._name, 1)
        row.addWidget(label("Длина", widget_role="muted"))
        row.addWidget(self._length)
        row.addWidget(label("Ширина", widget_role="muted"))
        row.addWidget(self._width)
        card.add_layout(row)

        buttons = QHBoxLayout()
        self._add_button = button(
            "Добавить в библиотеку",
            widget_role="primary",
            tooltip="Предмет с таким же названием будет заменён",
        )
        self._add_button.clicked.connect(self._add)
        clear = button("Очистить", tooltip="Очистить поля формы")
        clear.clicked.connect(self._clear_form)
        buttons.addWidget(self._add_button)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        card.add_layout(buttons)
        card.add(
            label(
                "Название — ключ: предмет с тем же названием заменяется, регистр не важен. "
                "Размеры задаются в метрах.",
                widget_role="muted",
            )
        )
        return card

    def _build_list(self) -> Card:
        card = Card("Мои предметы")
        self._empty_label = label(
            "Пока пусто: впишите название, длину и ширину — и нажмите «Добавить в библиотеку».",
            widget_role="muted",
        )
        card.add(self._empty_label)
        host = QWidget(self)
        self._rows_layout = QVBoxLayout(host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        card.add(host)
        card.add(
            label(
                "На вкладке «Движение» выберите предмет — его длину, ширину и половины "
                "можно сразу подставить в шаг.",
                widget_role="muted",
            )
        )
        return card

    # --- действия ---------------------------------------------------------

    def _add(self) -> None:
        try:
            item = ObjectSize(
                name=self._name.text(),
                length=self._length.value(),
                width=self._width.value(),
            )
            library = self._library.with_item(item)
        except AppError as exc:
            self.status_message.emit(str(exc))
            return
        self.library_changed.emit(library)

    def _clear_form(self) -> None:
        self._name.clear()
        self._length.setValue(DEFAULT_LENGTH)
        self._width.setValue(DEFAULT_WIDTH)
        self._name.setFocus()

    def _edit(self, name: str) -> None:
        item = self._library.find(name)
        if item is None:
            return
        self._name.setText(item.name)
        self._length.setValue(item.length)
        self._width.setValue(item.width)

    def _delete(self, name: str) -> None:
        item = self._library.find(name)
        if item is None:
            return
        self.library_changed.emit(self._library.without(item.name))

    # --- состояние --------------------------------------------------------

    def set_library(self, library: SizeLibrary) -> None:
        """Показать новую библиотеку (после сохранения или удаления)."""
        self._library = library
        self._refresh()

    def library(self) -> SizeLibrary:
        """Текущая библиотека (для тестов и окна)."""
        return self._library

    def row_names(self) -> list[str]:
        """Названия строк списка по порядку (для тестов)."""
        return [item.name for item in self._library.items]

    def press_delete(self, name: str) -> None:
        """Удалить предмет по названию (для тестов и окна)."""
        self._delete(name)

    def press_edit(self, name: str) -> None:
        """Перенести предмет в форму (для тестов)."""
        self._edit(name)

    def form_values(self) -> tuple[str, float, float]:
        """Значения формы: название, длина, ширина (для тестов)."""
        return self._name.text(), self._length.value(), self._width.value()

    def press_add(self) -> None:
        """Нажать «Добавить в библиотеку» (для тестов)."""
        self._add_button.click()

    def fill_form(self, name: str, length: float, width: float) -> None:
        """Заполнить форму (для тестов)."""
        self._name.setText(name)
        self._length.setValue(length)
        self._width.setValue(width)

    def _refresh(self) -> None:
        self._empty_label.setVisible(not self._library.items)
        if self._rows_layout is None:
            return
        while self._rows_layout.count():
            entry = self._rows_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        for item in self._library.items:
            self._rows_layout.addWidget(self._row(item))

    def _row(self, item: ObjectSize) -> QWidget:
        host = QWidget(self)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        active = self._library.active is not None and self._library.active.casefold() == item.key
        mark = "✓ " if active else ""
        row.addWidget(label(f"{mark}{item.text()}", widget_role="poseValue"), 1)
        edit = button("В форму", widget_role="small", tooltip="Перенести значения в поля выше")
        edit.clicked.connect(lambda _checked=False, name=item.name: self._edit(name))
        remove = button("Удалить", widget_role="small", tooltip="Убрать предмет из библиотеки")
        remove.clicked.connect(lambda _checked=False, name=item.name: self._delete(name))
        row.addWidget(edit)
        row.addWidget(remove)
        return host


def _size_spin(value: float) -> QDoubleSpinBox:
    """Поле размера: сантиметры — предел точности панели."""
    spin = QDoubleSpinBox()
    spin.setRange(MIN_SIZE_M, MAX_SIZE_M)
    spin.setDecimals(SIZE_DECIMALS)
    spin.setSingleStep(0.1)
    spin.setSuffix(" м")
    spin.setValue(value)
    spin.setMinimumWidth(SIZE_SPIN_WIDTH)
    return spin
