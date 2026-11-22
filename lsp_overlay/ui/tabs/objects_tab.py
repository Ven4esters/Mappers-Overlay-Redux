"""Вкладка «Объекты»: таблица измеренных предметов с поиском по названию."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsp_overlay.domain.catalog import Catalog, Dimension, ObjectSpec
from lsp_overlay.domain.errors import DomainError
from lsp_overlay.domain.formatting import format_length
from lsp_overlay.ui.widgets import make_button, make_label

COLUMNS: tuple[tuple[str, int], ...] = (
    ("Название", 190),
    ("Длина", 70),
    ("Ширина", 70),
    ("Толщина", 70),
)
EMPTY_TEXT = "—"
HINT = (
    "Габариты приходят из «Рулетки»: замерили — нажали «В размер». Таблица хранится в файле "
    "рядом с настройками: выберите строку, чтобы поставить длину шагом сдвига, когда объект "
    "уже использовался раньше."
)


class ObjectsTab(QWidget):
    """Каталог предметов: поиск, габариты, шаг из выбранной строки."""

    step_requested = Signal(float)
    delete_requested = Signal(str)
    object_saved = Signal(object)
    status_message = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = Catalog()
        self._dimensions: dict[Dimension, float] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self._build_form())
        layout.addWidget(self._build_search())
        layout.addWidget(self._build_table(), 1)
        layout.addWidget(self._build_actions())
        layout.addWidget(make_label(HINT, muted=True, wrap=True))

    # ------------------------------------------------------------------ сборка
    def _build_form(self) -> QGroupBox:
        group = QGroupBox("Новый предмет")
        column = QVBoxLayout(group)
        column.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Название, например «Забор 4 м»")
        self.edit_name.setToolTip("По этому названию предмет ищется в таблице")
        self.edit_name.returnPressed.connect(self._on_save_clicked)
        row.addWidget(self.edit_name, 1)
        self.btn_save = make_button(
            "Сохранить",
            "Записать предмет с измеренными габаритами в таблицу",
            object_name="successButton",
        )
        self.btn_save.clicked.connect(self._on_save_clicked)
        row.addWidget(self.btn_save)
        column.addLayout(row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)
        self._dimension_labels: dict[Dimension, QLabel] = {}
        for index, dimension in enumerate(Dimension):
            grid.addWidget(make_label(dimension.label, muted=True), 0, index)
            value = QLabel(EMPTY_TEXT)
            value.setObjectName("measureValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._dimension_labels[dimension] = value
            grid.addWidget(value, 1, index)
        column.addLayout(grid)
        return group

    def _build_search(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(make_label("Поиск", muted=True))
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("Название или его часть")
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.textChanged.connect(self._on_search_changed)
        row.addWidget(self.edit_search, 1)
        return holder

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([title for title, _width in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        header = self.table.horizontalHeader()
        for index, (_title, width) in enumerate(COLUMNS):
            self.table.setColumnWidth(index, width)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return self.table

    def _build_actions(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.btn_step = make_button(
            "Шаг = длина",
            "Поставить длину выбранного предмета шагом сдвига",
            object_name="primaryButton",
        )
        self.btn_step.clicked.connect(self._on_step_clicked)
        self.btn_delete = make_button("Удалить", "Убрать выбранный предмет из таблицы")
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        for button in (self.btn_step, self.btn_delete):
            button.setEnabled(False)
            row.addWidget(button, 1)
        self.lbl_count = QLabel("0")
        self.lbl_count.setObjectName("hintLabel")
        row.addWidget(self.lbl_count)
        return holder

    # ------------------------------------------------------------------ события
    def _on_search_changed(self, _text: str) -> None:
        self.show_catalog(self._catalog)

    def _on_selection_changed(self) -> None:
        has_selection = self.selected_spec() is not None
        self.btn_step.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)

    def _on_save_clicked(self) -> None:
        name = self.edit_name.text().strip()
        if not name:
            self.status_message.emit("Введите название предмета", "warning")
            return
        try:
            spec = ObjectSpec(
                name=name,
                length=self._dimensions.get(Dimension.LENGTH, 0.0),
                width=self._dimensions.get(Dimension.WIDTH, 0.0),
                thickness=self._dimensions.get(Dimension.THICKNESS, 0.0),
            )
        except DomainError as error:
            self.status_message.emit(str(error), "error")
            return
        self.object_saved.emit(spec)

    def _on_step_clicked(self) -> None:
        spec = self.selected_spec()
        if spec is None:
            self.status_message.emit("Выберите предмет в таблице", "warning")
            return
        self.step_requested.emit(spec.length)

    def _on_delete_clicked(self) -> None:
        spec = self.selected_spec()
        if spec is None:
            self.status_message.emit("Выберите предмет в таблице", "warning")
            return
        self.delete_requested.emit(spec.name)

    # ------------------------------------------------------------------- вывод
    def set_pending(self, dimensions: dict[Dimension, float]) -> None:
        """Показывает габариты, измеренные во вкладке «Рулетка»."""
        self._dimensions = dict(dimensions)
        for dimension, label in self._dimension_labels.items():
            value = self._dimensions.get(dimension)
            label.setText(EMPTY_TEXT if value is None else f"{format_length(value, 3)} м")

    def dimension_text(self, dimension: Dimension) -> str:
        """Текст габарита в форме нового предмета."""
        return self._dimension_labels[dimension].text()

    def clear_form(self) -> None:
        """Очищает название и измеренные габариты после сохранения."""
        self.edit_name.clear()
        self.set_pending({})

    def show_catalog(self, catalog: Catalog) -> None:
        """Показывает предметы, подходящие под строку поиска."""
        self._catalog = catalog
        items = catalog.find(self.edit_search.text())
        self.table.blockSignals(True)
        self.table.setRowCount(len(items))
        for row, spec in enumerate(items):
            for column, text in enumerate(_row_texts(spec)):
                cell = QTableWidgetItem(text)
                if column > 0:
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, column, cell)
        self.table.blockSignals(False)
        self.lbl_count.setText(f"{len(items)} из {len(catalog.objects)}")
        self._on_selection_changed()

    def selected_spec(self) -> ObjectSpec | None:
        """Предмет из выделенной строки."""
        row = self.table.currentRow()
        if row < 0:
            return None
        name_item = self.table.item(row, 0)
        if name_item is None:
            return None
        return self._catalog.get(name_item.text())

    def select_name(self, name: str) -> bool:
        """Выделяет строку с нужным названием; ``True``, если нашла."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text().casefold() == name.strip().casefold():
                self.table.selectRow(row)
                return True
        return False


def _row_texts(spec: ObjectSpec) -> tuple[str, str, str, str]:
    return (
        spec.name,
        f"{format_length(spec.length, 2)} м",
        f"{format_length(spec.width, 2)} м",
        f"{format_length(spec.thickness, 2)} м",
    )
