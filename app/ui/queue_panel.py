"""Capture queue panel with drag-and-drop. / Панель очереди с drag-and-drop."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QVBoxLayout, QWidget,
)

from app.cache import guess_ext, mime_for_suffix
from app.i18n import tr
from app import queue_store

logger = logging.getLogger("screensaver.queue")


@dataclass
class ShotItem:
    """One queued screenshot. / Один скрин в очереди."""

    id: str
    filename: str
    data: bytes
    mime: str = "image/png"
    cache_name: str = ""  # file name inside cache/shots (content-addressed)

    @classmethod
    def create(cls, filename: str, data: bytes, mime: str = "image/png") -> "ShotItem":
        return cls(id=uuid.uuid4().hex, filename=filename, data=data, mime=mime)

    @property
    def ext(self) -> str:
        return guess_ext(self.mime, self.filename).lstrip(".")

    @property
    def size_label(self) -> str:
        kb = len(self.data) / 1024
        return f"{kb:,.0f} КБ" if kb < 1024 else f"{kb / 1024:,.1f} МБ"


class _DropList(QListWidget):
    filesDropped = Signal(list)
    deleteRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QPixmap(150, 110).size())
        self.setGridSize(QPixmap(176, 158).size())
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setWordWrap(True)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Delete:
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._first_local_image(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._first_local_image(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = self._first_local_image(event.mimeData())
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _first_local_image(mime) -> list[str]:
        if not mime.hasUrls():
            return []
        suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        paths = []
        for url in mime.urls():
            path = url.toLocalFile()
            if path and any(path.lower().endswith(s) for s in suffixes):
                paths.append(path)
        return paths


class QueuePanel(QWidget):
    """Toolbar + thumbnail grid. / Тулбар + сетка миниатюр."""

    captureRequested = Signal(str)           # 'fullscreen' | 'window' | 'region'
    openFilesRequested = Signal()
    changed = Signal()
    # UI asks for confirmation first (main window shows the dialog) — the panel
    # never deletes interactively on its own. / Интерактивное удаление — через
    # главное окно (с подтверждением); прямых вызовов методов удаления нет.
    removeRequested = Signal()
    clearRequested = Signal()
    deleteCheckedRequested = Signal()
    catboxRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shots: dict[str, ShotItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._capture_button = QPushButton(f"📷  {tr('queue.capture')}", self)
        self._capture_button.setObjectName("Primary")
        self._capture_button.setToolTip(tr("queue.capture_hint"))
        capture_menu = QMenu(self._capture_button)
        capture_menu.addAction(tr("capture.fullscreen"), lambda: self.captureRequested.emit("fullscreen"))
        capture_menu.addAction(tr("capture.active_window"), lambda: self.captureRequested.emit("window"))
        capture_menu.addAction(tr("capture.region"), lambda: self.captureRequested.emit("region"))
        self._capture_button.setMenu(capture_menu)
        self._capture_button.setStyleSheet("padding: 8px 10px; font-size: 12px;")
        toolbar.addWidget(self._capture_button)

        self._add_files = QPushButton(f"📂  {tr('queue.files_short')}", self)
        self._add_files.setObjectName("ToolbarButton")
        self._add_files.clicked.connect(self.openFilesRequested.emit)
        toolbar.addWidget(self._add_files)

        self._catbox = QPushButton(f"{tr('queue.upload_catbox')}", self)
        self._catbox.setToolTip(tr("queue.upload_catbox_tooltip"))
        self._catbox.clicked.connect(self.catboxRequested)
        toolbar.addWidget(self._catbox)

        self._remove = QPushButton(tr("queue.remove_short"), self)
        self._remove.setObjectName("ToolbarButton")
        self._remove.setToolTip(tr("queue.remove_selected"))
        self._remove.clicked.connect(self.removeRequested)
        toolbar.addWidget(self._remove)

        self._clear = QPushButton(tr("queue.clear"), self)
        self._clear.setObjectName("Ghost")
        self._clear.setStyleSheet("font-size: 12px; padding: 8px 10px;")
        self._clear.clicked.connect(self.clearRequested)
        toolbar.addWidget(self._clear)
        toolbar.addStretch(1)
        self._counter = QLabel("0", self)
        self._counter.setObjectName("Dim")
        toolbar.addWidget(self._counter)
        layout.addLayout(toolbar)

        self._list = _DropList(self)
        self._list.itemChanged.connect(lambda _item: self.changed.emit())
        self._list.filesDropped.connect(self._on_files_dropped)
        self._list.deleteRequested.connect(self.deleteCheckedRequested)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._list, stretch=1)

        self._empty = QLabel(tr("queue.empty"), self)
        self._empty.setObjectName("Subtitle")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty, stretch=1)
        self._update_empty_state()

    # ------------------------------------------------------------- content
    def add(self, shots: list[ShotItem], *, checked: list[bool] | None = None) -> int:
        added = 0
        self._list.blockSignals(True)
        for index, shot in enumerate(shots):
            if not shot.cache_name:
                try:
                    shot.cache_name = queue_store.store_shot(shot.data, shot.filename)
                except OSError:
                    logger.exception("could not store shot %r in the cache", shot.filename)
            image = QImage.fromData(shot.data)
            if image.isNull():
                continue
            scaled = QPixmap.fromImage(image).scaled(
                150, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # reserve a left gutter for the check indicator so its box never
            # sits on top of the photo (Qt paints the indicator at the icon's
            # top-left corner) / слот слева под чекбокс — он больше не на фото
            pixmap = QPixmap(150, 110)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.drawPixmap(
                26 + (124 - scaled.width()) // 2, (110 - scaled.height()) // 2, scaled)
            painter.end()
            item = QListWidgetItem(QIcon(pixmap), shot.filename)
            item.setData(Qt.UserRole, shot.id)
            item.setToolTip(f"{shot.filename}\n{image.width()}×{image.height()} · {shot.size_label}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            state = Qt.Checked if (checked[index] if checked else True) else Qt.Unchecked
            item.setCheckState(state)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self._list.addItem(item)
            self._shots[shot.id] = shot
            added += 1
        self._list.blockSignals(False)
        self._update_empty_state()
        self._persist()
        self.changed.emit()
        return added

    def restore_from_disk(self) -> int:
        """Rebuild the queue from cache/shots + queue.json. / Восстановить очередь."""
        entries = queue_store.restore_entries()
        shots, states = [], []
        for entry in entries:
            cache_path = queue_store.shot_path(str(entry.get("file", "")))
            try:
                data = cache_path.read_bytes()
            except OSError:
                logger.warning("queue entry %r unreadable — dropped", cache_path)
                continue
            item = ShotItem(id=str(entry.get("id") or uuid.uuid4().hex),
                            filename=str(entry.get("filename", "shot.png")),
                            data=data,
                            mime=str(entry.get("mime", "image/png")),
                            cache_name=cache_path.name)
            shots.append(item)
            states.append(bool(entry.get("checked", True)))
        if not shots:
            return 0
        restored = self.add(shots, checked=states)
        logger.info("queue restored from the cache: %d shot(s)", restored)
        return restored

    def _persist(self) -> None:
        entries = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            shot = self._shots.get(item.data(Qt.UserRole))
            if shot is None or not shot.cache_name:
                continue
            entries.append(queue_store.make_entry(
                shot.id, shot.filename, shot.cache_name, shot.mime,
                item.checkState() == Qt.Checked))
        try:
            queue_store.write_entries(entries)
        except OSError:
            logger.exception("could not persist the queue index")

    # -------------------------------------------------- select / deselect all
    def set_all_checked(self, state: bool) -> int:
        """Tick or untick every item; returns how many changed. / Снять|выделить все."""
        target = Qt.Checked if state else Qt.Unchecked
        changed = 0
        self._list.blockSignals(True)
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.checkState() != target:
                item.setCheckState(target)
                changed += 1
        self._list.blockSignals(False)
        self._persist()
        self.changed.emit()
        return changed

    def remove_ids(self, ids: list[str]) -> int:
        """Remove exactly the given shot ids (send flow). / Удалить ровно указанные."""
        wanted = set(ids)
        doomed = [self._list.item(i) for i in range(self._list.count())
                  if self._list.item(i).data(Qt.UserRole) in wanted]
        for item in doomed:
            self._drop_item(item)
        if doomed:
            self._update_empty_state()
            self._persist()
            self.changed.emit()
        return len(doomed)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self._list)
        menu.addAction(tr("queue.select_all"), lambda: self.set_all_checked(True))
        menu.addAction(tr("queue.deselect_all"), lambda: self.set_all_checked(False))
        menu.exec(self._list.mapToGlobal(pos))

    # ------------------------------------------------------ deletion helpers
    def checked_count(self) -> int:
        return sum(1 for i in range(self._list.count())
                   if self._list.item(i).checkState() == Qt.Checked)

    def selected_count(self) -> int:
        return len(self._list.selectedItems())

    def total_count(self) -> int:
        return self._list.count()

    def remove_checked(self) -> int:
        """Delete every tick-checked item; returns how many. / Удалить все с галочкой."""
        doomed = [self._list.item(i) for i in range(self._list.count())
                  if self._list.item(i).checkState() == Qt.Checked]
        for item in doomed:
            self._drop_item(item)
        self._update_empty_state()
        self._persist()
        self.changed.emit()
        return len(doomed)

    def checked_shots(self) -> list[ShotItem]:
        result = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.checkState() == Qt.Checked:
                shot = self._shots.get(item.data(Qt.UserRole))
                if shot:
                    result.append(shot)
        return result

    def remove_selected(self) -> int:
        selected = list(self._list.selectedItems())
        for item in selected:
            self._drop_item(item)
        self._update_empty_state()
        self._persist()
        self.changed.emit()
        return len(selected)

    def clear(self) -> int:
        count = self._list.count()
        while self._list.count():
            self._drop_item(self._list.item(0))
        self._update_empty_state()
        self._persist()
        self.changed.emit()
        return count

    def _drop_item(self, item: QListWidgetItem) -> None:
        self._shots.pop(item.data(Qt.UserRole), None)
        row = self._list.row(item)
        self._list.takeItem(row)

    def _on_files_dropped(self, paths: list[str]) -> None:
        shots = []
        for path in paths:
            try:
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError:
                continue
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            shots.append(ShotItem.create(name, data, mime_for_suffix(name.rsplit(".", 1)[-1])))
        if shots:
            self.add(shots)

    def _update_empty_state(self) -> None:
        empty = self._list.count() == 0
        self._empty.setVisible(empty)
        self._list.setVisible(not empty)
        self._counter.setText(f"{self._list.count()}")
