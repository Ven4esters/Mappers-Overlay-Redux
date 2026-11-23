"""Вкладка навигации: координаты, шаг, выбор предмета и крестовина из восьми стрелок."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QLocale, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from map_overlay.domain.formatting import rounded
from map_overlay.domain.movement import (
    COORD_DECIMALS,
    MAX_STEP,
    MIN_STEP,
    alt_hint,
    validate_step,
)
from map_overlay.domain.pose import Pose
from map_overlay.domain.search import NameSearch
from map_overlay.domain.sizes import SIZE_USES, ObjectSize, SizeLibrary, SizeUse
from map_overlay.errors import ValidationError
from map_overlay.ui.widgets import (
    LABEL_COLUMN_WIDTH,
    ROW_SPACING,
    SECTION_GAP,
    Card,
    DirectionPad,
    PoseGrid,
    button,
    label,
)

STEP_PRESETS: Final[tuple[str, ...]] = ("0.1", "0.25", "0.5", "1", "2", "5", "10")
SIZE_COMBO_WIDTH: Final = 150
SIZE_COMBO_CHARS: Final = 14
# Сколько символов названия гарантированно видно в списке предметов.
NO_SIZE_TEXT: Final = "— не выбран —"
STEP_DECIMALS: Final = 3
_HINTS: Final = (
    "Одна стрелка — один шаг; то же самое на клавишах Num 8/2/4/6 и Num 7/9/1/3.\n"
    "Зажмите клавишу — шаги идут друг за другом, отпустите — движение остановится.\n"
    "Одно нажатие Alt включает режим высоты: Num 8 — вверх, Num 2 — вниз\n"
    "(при RY ≠ 0 шаг идёт в плоскости X/Z).\n"
    "Остальные клавиши не меняются: Num 4/6 — по горизонтали, диагонали — по наклону\n"
    "предмета.\n"
    "Держать Alt не нужно: пока он зажат, игра не применяет правки панели."
)
# Подсказки под крестовиной — списком с выделенными клавишами: их читают в работе,
# поэтому длинный абзац здесь неудобен.


class MovementTab(QWidget):
    """Считать координаты, выбрать предмет и двигать его стрелками."""

    capture_requested = Signal()
    confirm_requested = Signal()
    move_requested = Signal(object, float)
    tilt_toggled = Signal(bool)
    size_selected = Signal(object)

    def __init__(self, *, default_step: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pose: Pose | None = None
        self._tilt = False
        self._library = SizeLibrary()
        self._size_buttons: list[QPushButton] = []
        self._size_engine = NameSearch()
        self._build(default_step)

    def _build(self, default_step: float) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(SECTION_GAP)
        self._pose_card = self._build_pose_card()
        layout.addWidget(self._pose_card)
        self._move_card = self._build_move_card(default_step)
        layout.addWidget(self._move_card)
        self._warning = label("", widget_role="warn")
        self._warning.hide()
        layout.addWidget(self._warning)
        layout.addStretch(1)
        self._pad.set_enabled(False)

    def _build_pose_card(self) -> Card:
        """Карточка координат и углов с кнопками «Считать» и «Сохранить F»."""
        card = Card("Координаты и углы")
        self._grid = PoseGrid(self)
        card.add(self._grid)
        row = QHBoxLayout()
        self._capture_button = button("Считать", widget_role="primary")
        self._capture_button.clicked.connect(self.capture_requested.emit)
        self._capture_button.setToolTip("Прочитать все шесть полей панели")
        self._confirm_button = button("Сохранить F")
        self._confirm_button.clicked.connect(self.confirm_requested.emit)
        self._confirm_button.setToolTip(
            "Вставить значения, кликнуть в пустое место панели и нажать F"
        )
        row.addWidget(self._capture_button)
        row.addWidget(self._confirm_button)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _build_move_card(self, default_step: float) -> Card:
        """Карточка сдвига: крестовина, шаг, режим высоты и подсказки."""
        card = Card("Сдвиг предмета", hint=_HINTS)
        self._pad = DirectionPad(self)
        self._pad.direction_clicked.connect(self._request_move)
        card.add(self._pad)
        card.add_layout(self._build_step_row(default_step))
        self._picker = self._build_picker()
        card.add(self._picker)
        card.add(self._size_info)
        card.add_layout(self._build_mode_row())
        return card

    def _build_step_row(self, default_step: float) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(ROW_SPACING)
        # Подпись занимает ту же колонку, что «Поиск» и «Предмет»: поля начинаются с одного
        # места, и строка шага не выглядит сдвинутой влево.
        step_label = label("Шаг", widget_role="muted")
        step_label.setMinimumWidth(LABEL_COLUMN_WIDTH)
        row.addWidget(step_label)
        self._step_combo = QComboBox(self)
        self._step_combo.setEditable(True)
        self._step_combo.addItems(STEP_PRESETS)
        self._step_combo.setCurrentText(_format_step(default_step))
        self._step_combo.setValidator(QDoubleValidator(MIN_STEP, MAX_STEP, STEP_DECIMALS, self))
        self._step_combo.setLocale(QLocale.c())
        self._step_combo.setMinimumWidth(96)
        row.addWidget(self._step_combo)
        row.addWidget(label("м", widget_role="muted"))
        row.addStretch(1)
        return row

    def _build_picker(self) -> QWidget:
        """Поиск и выбор предмета: подписи в одной колонке, поля — во всю ширину.

        «Поиск» и «Предмет» стоят друг под другом и начинаются с одного места, а счётчик
        найденного ушёл под поле поиска: рядом с полем он сжимал его до половины карточки.
        """
        self._size_info = label("", widget_role="muted")
        holder = QWidget(self)
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(ROW_SPACING)
        grid.setVerticalSpacing(ROW_SPACING)
        grid.setColumnMinimumWidth(0, LABEL_COLUMN_WIDTH)
        grid.setColumnStretch(1, 1)

        self._size_search = QLineEdit(holder)
        self._size_search.setPlaceholderText("Поиск: слова названия или номер из диапазона")
        self._size_search.setClearButtonEnabled(True)
        self._size_search.textChanged.connect(self._rebuild_size_combo)
        self._size_hint = label("", widget_role="hint")
        self._size_hint.setWordWrap(True)

        self._size_combo = QComboBox(holder)
        self._size_combo.setMinimumWidth(SIZE_COMBO_WIDTH)
        # Ширина списка не зависит от самого длинного названия: иначе «Стена March,
        # TID, Hood, Soup, New, 01-39» растягивала окно и ломала мини-версию.
        self._size_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._size_combo.setMinimumContentsLength(SIZE_COMBO_CHARS)
        self._size_combo.currentIndexChanged.connect(self._size_changed)

        buttons = QHBoxLayout()
        buttons.setSpacing(ROW_SPACING)
        for use in SIZE_USES:
            item = button(use.label, widget_role="small", tooltip=use.hint)
            item.clicked.connect(lambda _checked=False, kind=use: self.apply_size(kind))
            self._size_buttons.append(item)
            buttons.addWidget(item)
        buttons.addStretch(1)

        grid.addWidget(label("Поиск", widget_role="muted"), 0, 0)
        grid.addWidget(self._size_search, 0, 1)
        grid.addWidget(self._size_hint, 1, 1)
        grid.addWidget(label("Предмет", widget_role="muted"), 2, 0)
        grid.addWidget(self._size_combo, 2, 1)
        # Кнопки шага — под полем предмета: в одну строку с ним они не помещались в окно
        # шириной 640, и правый край уходил за границу карточки.
        grid.addLayout(buttons, 3, 1)
        return holder

    def _build_mode_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._tilt_box = QCheckBox("Режим высоты", self)
        self._tilt_box.setToolTip(
            "Num 8 поднимает предмет, Num 2 опускает. Остальные клавиши работают как "
            "обычно. То же делает одно нажатие Alt."
        )
        self._tilt_box.toggled.connect(self.tilt_toggled.emit)
        row.addWidget(self._tilt_box)
        row.addStretch(1)
        self._mode_label = label("8/2 — вперёд/назад", widget_role="muted")
        self._mode_label.setWordWrap(False)
        row.addWidget(self._mode_label)
        return row

    def _request_move(self, direction: object) -> None:
        try:
            step = self.current_step()
        except ValidationError as exc:
            self.set_warning(str(exc))
            return
        self.move_requested.emit(direction, step)

    def current_step(self) -> float:
        """Шаг из поля ввода.

        Raises:
            ValidationError: если число недопустимо.
        """
        raw = self._step_combo.currentText().replace(",", ".").strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValidationError("Шаг должен быть числом") from exc
        return validate_step(value)

    def set_compact(self, enabled: bool) -> None:
        """Свернуть вкладку до крестовины, шага и выбора предмета (мини-версия окна).

        В мини-версии прячется всё, что нужно только для настройки шага: координаты,
        подсказки, поиск, выбор предмета и кнопки «Длина/Ширина/½». Без этого строки
        не помещались в узкое окно, и крестовина обрезалась справа.
        """
        self._pose_card.setVisible(not enabled)
        # Поиск и выбор предмета прячутся целиком: в мини-версии нечего искать — она про то,
        # чтобы двигать предмет стрелками, а выбор предмета задаёт шаг.
        self._picker.setVisible(not enabled)

    def is_compact(self) -> bool:
        """Скрыты ли координаты и подсказки (для тестов)."""
        return not self._pose_card.isVisibleTo(self)

    def item_picker_visible(self) -> bool:
        """Видны ли поиск и выбор предмета (для тестов)."""
        return self._picker.isVisibleTo(self)

    def press_capture(self) -> None:
        """Нажать «Считать» (для тестов и будущих горячих клавиш)."""
        self._capture_button.click()

    def set_sizes(self, library: SizeLibrary) -> None:
        """Показать библиотеку размеров и выбранный предмет.

        Список перестраивается из фильтра поиска; сигналы списка на это время выключены,
        иначе перестройка внутри собственного сигнала выбора запускала бы новый выбор.
        """
        self._library = library
        self._size_engine.reset()
        self._rebuild_size_combo()

    def _matched_size_names(self) -> list[str]:
        """Предметы, подходящие под запрос поиска (в порядке точности)."""
        names = [item.name for item in self._library.items]
        return self._size_engine.match(names, self._size_search.text())

    def _visible_size_names(self) -> list[str]:
        """Строки списка: найденные предметы, а выбранный — всегда, даже если не найден."""
        matched = self._matched_size_names()
        active = self._library.active_item
        if active is not None and active.name not in matched:
            return [active.name, *matched]
        return matched

    def _rebuild_size_combo(self, _text: str = "") -> None:
        """Перестроить список предметов под текущий запрос поиска.

        Содержимое меняется только когда меняется набор строк: выбор предмета приходит из
        этого же списка, и перестройка внутри его сигнала — лишний риск.
        """
        names = self._visible_size_names()
        active = self._library.active_item
        if names != self._size_names():
            self._size_combo.blockSignals(True)
            self._size_combo.clear()
            self._size_combo.addItem(NO_SIZE_TEXT)
            self._size_combo.addItems(names)
            self._size_combo.blockSignals(False)
        self._size_combo.blockSignals(True)
        index = 0 if active is None else self._size_combo.findText(active.name)
        self._size_combo.setCurrentIndex(max(0, index))
        self._size_combo.blockSignals(False)
        self._size_combo.setEnabled(bool(names))
        for widget in self._size_buttons:
            widget.setEnabled(active is not None)
        self._size_info.setText(_size_info(active))
        self._size_hint.setText(self._size_hint_text())

    def _size_hint_text(self) -> str:
        """Подсказка рядом с поиском: сколько предметов нашлось."""
        total = len(self._library.items)
        if not total:
            return "Библиотека пуста: предметы добавляются на вкладке «Размеры»"
        query = self._size_search.text().strip()
        if not query:
            return f"Предметов: {total}"
        matched = self._matched_size_names()
        if not matched:
            return f"Ничего не найдено по запросу «{query}»"
        note = f" · номер совпал {self._size_engine.note}" if self._size_engine.loose else ""
        return f"Найдено: {len(matched)} из {total}{note}"

    def _size_names(self) -> list[str]:
        """Названия предметов в списке без строки «не выбран»."""
        return [self._size_combo.itemText(index) for index in range(1, self._size_combo.count())]

    def _size_changed(self, index: int) -> None:
        """Пользователь выбрал другой предмет (или «не выбран»)."""
        if index <= 0:
            self.size_selected.emit(None)
            return
        self.size_selected.emit(self._size_combo.itemText(index))

    def apply_size(self, use: SizeUse) -> bool:
        """Подставить размер выбранного предмета в шаг.

        Returns:
            ``True``, если шаг изменён; ``False`` — предмет не выбран или шаг недопустим.
        """
        active = self._library.active_item
        if active is None:
            self.set_warning("Сначала выберите предмет: размеры задаются на вкладке «Размеры»")
            return False
        value = use.value_for(active)
        try:
            step = validate_step(value)
        except ValidationError as exc:
            self.set_warning(f"{use.label} «{active.name}» — {value:g} м: {exc}")
            return False
        self._step_combo.setCurrentText(_format_step(rounded(step, STEP_DECIMALS)))
        self.set_warning("")
        self._size_info.setText(f"{active.name}: шаг = {use.label.lower()} ({step:g} м)")
        return True

    def size_names(self) -> list[str]:
        """Названия в списке предметов (для тестов)."""
        return [self._size_combo.itemText(index) for index in range(self._size_combo.count())]

    def press_size_search(self, query: str) -> None:
        """Ввести запрос в поиск предметов (для тестов)."""
        self._size_search.setText(query)

    def size_search_hint(self) -> str:
        """Подсказка рядом с поиском предметов (для тестов)."""
        return self._size_hint.text()

    def visible_size_names(self) -> list[str]:
        """Предметы в списке с учётом поиска, без строки «не выбран» (для тестов)."""
        return self._visible_size_names()

    def select_size(self, name: str) -> None:
        """Выбрать предмет в списке (для тестов)."""
        self._size_combo.setCurrentIndex(self._size_combo.findText(name))

    def press_size_button(self, use: SizeUse) -> QPushButton:
        """Кнопка «в шаг» для проверки нажатия (для тестов)."""
        return self._size_buttons[SIZE_USES.index(use)]

    def set_default_step(self, step: float) -> None:
        """Показать новый шаг по умолчанию."""
        self._step_combo.setCurrentText(_format_step(step))

    def set_pose(self, pose: Pose | None) -> None:
        """Обновить координаты и доступность стрелок."""
        self._pose = pose
        self._grid.set_pose(pose)
        self._pad.set_enabled(pose is not None)
        self._refresh_mode()

    def step_text(self) -> str:
        """Шаг, как он введён в поле (для журнала действий и тестов)."""
        return self._step_combo.currentText()

    def mode_text(self) -> str:
        """Подпись режима движения (для тестов)."""
        return self._mode_label.text()

    def set_tilt(self, enabled: bool) -> None:
        """Показать, включён ли режим высоты."""
        self._tilt = enabled
        self._pad.set_alt_mode(enabled)
        self._refresh_mode()

    def _refresh_mode(self) -> None:
        if self._tilt_box.isChecked() != self._tilt:
            self._tilt_box.blockSignals(True)
            self._tilt_box.setChecked(self._tilt)
            self._tilt_box.blockSignals(False)
        self._mode_label.setText(self._mode_text())
        self._mode_label.setProperty("role", "ok" if self._tilt else "muted")
        self._mode_label.style().unpolish(self._mode_label)
        self._mode_label.style().polish(self._mode_label)

    def _mode_text(self) -> str:
        if not self._tilt:
            return "8/2 — вперёд/назад"
        return alt_hint()

    def press_confirm(self) -> None:
        """Нажать «Сохранить F» (для тестов)."""
        self._confirm_button.click()

    def set_busy(self, busy: bool) -> None:
        """Заблокировать управление на время обмена с панелью."""
        self._capture_button.setEnabled(not busy)
        self._confirm_button.setEnabled(not busy)
        self._pad.set_enabled(not busy and self._pose is not None)

    def arrow(self, direction: object) -> QPushButton:
        """Кнопка стрелки (для тестов)."""
        return self._pad.button(direction)  # type: ignore[arg-type]

    def warning_text(self) -> str:
        """Текст предупреждения (пустая строка — предупреждения нет)."""
        return self._warning.text()

    def set_warning(self, text: str) -> None:
        """Показать или скрыть предупреждение под карточкой сдвига."""
        self._warning.setText(text)
        self._warning.setVisible(bool(text))


def _format_step(step: float) -> str:
    return f"{step:g}"


def _size_info(size: ObjectSize | None) -> str:
    """Подпись под строкой предмета: габариты выбранного или подсказка."""
    if size is None:
        return "Выберите предмет, чтобы подставить его размер в шаг"
    return f"Длина {size.length:g} м · ширина {size.width:g} м"


def pose_text(pose: Pose) -> str:
    """Координаты одной строкой для статуса."""
    x = rounded(pose.x, COORD_DECIMALS)
    y = rounded(pose.y, COORD_DECIMALS)
    z = rounded(pose.z, COORD_DECIMALS)
    return f"X {x:.3f} · Y {y:.3f} · Z {z:.3f}"
