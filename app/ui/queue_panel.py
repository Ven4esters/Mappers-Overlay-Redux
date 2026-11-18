"""Capture queue panel with drag-and-drop. / Панель очереди с drag-and-drop."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QVBoxLayout, QWidget,
)

from app.cache import guess_ext
from app.i18n import tr


@dataclass
class ShotItem:
    """One queued screenshot. / Один скрин в очереди."""

    id: str
    filename: str
    data: bytes
    mime: str = "image/png"

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
        toolbar.addWidget(self._capture_button)

        self._add_files = QPushButton(f"📂  {tr('queue.add_files')}", self)
        self._add_files.clicked.connect(self.openFilesRequested.emit)
        toolbar.addWidget(self._add_files)

        self._remove = QPushButton(tr("queue.remove_selected"), self)
        self._remove.clicked.connect(self.remove_selected)
        toolbar.addWidget(self._remove)

        self._clear = QPushButton(tr("queue.clear"), self)
        self._clear.setObjectName("Ghost")
        self._clear.clicked.connect(self.clear)
        toolbar.addWidget(self._clear)
        toolbar.addStretch(1)
        self._counter = QLabel("0", self)
        self._counter.setObjectName("Dim")
        toolbar.addWidget(self._counter)
        layout.addLayout(toolbar)

        self._list = _DropList(self)
        self._list.itemChanged.connect(lambda _item: self.changed.emit())
        self._list.filesDropped.connect(self._on_files_dropped)
        layout.addWidget(self._list, stretch=1)

        self._empty = QLabel(tr("queue.empty"), self)
        self._empty.setObjectName("Subtitle")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)
        self._update_empty_state()

    # ------------------------------------------------------------- content
    def add(self, shots: list[ShotItem]) -> None:
        for shot in shots:
            image = QImage.fromData(shot.data)
            if image.isNull():
                continue
            pixmap = QPixmap.fromImage(image).scaled(
                150, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = QListWidgetItem(QIcon(pixmap), shot.filename)
            item.setData(Qt.UserRole, shot.id)
            item.setToolTip(f"{shot.filename}\n{image.width()}×{image.height()} · {shot.size_label}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self._list.addItem(item)
            self._shots[shot.id] = shot
        self._update_empty_state()
        self.changed.emit()

    def all_shots(self) -> list[ShotItem]:
        return list(self._shots.values())

    def checked_shots(self) -> list[ShotItem]:
        result = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.checkState() == Qt.Checked:
                shot = self._shots.get(item.data(Qt.UserRole))
                if shot:
                    result.append(shot)
        return result

    def remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._drop_item(item)
        self._update_empty_state()
        self.changed.emit()

    def clear(self) -> None:
        while self._list.count():
            self._drop_item(self._list.item(0))
        self._update_empty_state()
        self.changed.emit()

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
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp"}.get(
                name.rsplit(".", 1)[-1].lower(), "image/png")
            shots.append(ShotItem.create(name, data, mime))
        if shots:
            self.add(shots)

    def _update_empty_state(self) -> None:
        empty = self._list.count() == 0
        self._empty.setVisible(empty)
        self._list.setVisible(not empty)
        self._counter.setText(f"{self._list.count()}")
