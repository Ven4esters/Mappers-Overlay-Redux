"""Album sidebar: profile picker + album registry navigation. / Сайдбар альбомов."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QVBoxLayout,
)

from app.i18n import tr
from app.models import Album, WebhookProfile
from app.store import ConfigStore


class AlbumSidebar(QFrame):
    """Left navigation: profiles, album search + list, create/attach actions.
    Левая колонка: профиль, поиск/список альбомов, создание и привязка."""

    profileChanged = Signal(str)       # profile_id
    albumSelected = Signal(str)        # album_id
    createRequested = Signal()
    attachRequested = Signal()
    discoverRequested = Signal()
    openRequested = Signal(str)
    renameRequested = Signal(str)
    forgetRequested = Signal(str)
    bbCodeRequested = Signal(str)
    settingsRequested = Signal()
    historyRequested = Signal()

    def __init__(self, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(258)
        self._store = store
        self._albums: list[Album] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(8)

        layout.addWidget(self._label(tr("sidebar.profile")))
        self._profile_combo = QComboBox(self)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_index)
        layout.addWidget(self._profile_combo)

        layout.addWidget(self._label(tr("sidebar.albums")))
        self._search = QLineEdit(self)
        self._search.setPlaceholderText(tr("sidebar.search_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._list = QListWidget(self)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_menu)
        self._list.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._list, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        create = QPushButton(f"＋ {tr('album.new')}", self)
        create.setObjectName("Primary")
        create.clicked.connect(self.createRequested.emit)
        actions.addWidget(create, stretch=1)
        attach = QPushButton(f"⭳ {tr('album.attach')}", self)
        attach.clicked.connect(self.attachRequested.emit)
        actions.addWidget(attach, stretch=1)
        layout.addLayout(actions)

        discover = QPushButton(f"🔍  {tr('album.discover')}", self)
        discover.setObjectName("Ghost")
        discover.setToolTip(tr("album.discover_hint"))
        discover.clicked.connect(self.discoverRequested.emit)
        layout.addWidget(discover)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        history = QPushButton(f"🕘  {tr('nav.history')}", self)
        history.setObjectName("Ghost")
        history.clicked.connect(self.historyRequested.emit)
        footer.addWidget(history, stretch=1)
        settings = QPushButton(f"⚙  {tr('nav.settings')}", self)
        settings.setObjectName("Ghost")
        settings.clicked.connect(self.settingsRequested.emit)
        footer.addWidget(settings, stretch=1)
        layout.addLayout(footer)

    # ------------------------------------------------------------- content
    def refresh_profiles(self, profiles: list[WebhookProfile], active_id: str) -> None:
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for profile in profiles:
            icon = "🏟" if profile.is_forum else "💬"
            label = f"{icon}  {profile.name}"
            self._profile_combo.addItem(label, profile.id)
        index = next((i for i, p in enumerate(profiles) if p.id == active_id), 0 if profiles else -1)
        if index >= 0:
            self._profile_combo.setCurrentIndex(index)
        self._profile_combo.setEnabled(bool(profiles))
        self._profile_combo.blockSignals(False)

    def refresh_albums(self, albums: list[Album], keep_selection: bool = True) -> None:
        selected = self.selected_album_id() if keep_selection else ""
        self._albums = list(albums)
        self._apply_filter(self._search.text(), selected)

    def selected_album_id(self) -> str:
        item = self._list.currentItem()
        return str(item.data(Qt.UserRole)) if item else ""

    def select_album(self, album_id: str) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.UserRole) == album_id:
                self._list.setCurrentItem(item)
                return

    # -------------------------------------------------------------- events
    def _on_profile_index(self, index: int) -> None:
        profile_id = self._profile_combo.itemData(index)
        if profile_id:
            self.profileChanged.emit(str(profile_id))

    def _apply_filter(self, text: str, keep: str = "") -> None:
        needle = text.strip().lower()
        self._list.blockSignals(True)
        self._list.clear()
        for album in self._albums:
            if needle and needle not in album.name.lower():
                continue
            item = QListWidgetItem(album.name)
            item.setData(Qt.UserRole, album.id)
            item.setToolTip(tr("album.stats", messages=album.messages_sent,
                               shots=album.shots_sent, number=album.last_number))
            self._list.addItem(item)
        self._list.blockSignals(False)
        if keep:
            self.select_album(keep)

    def _on_selection(self) -> None:
        album_id = self.selected_album_id()
        if album_id:
            self.albumSelected.emit(album_id)

    def _show_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        album_id = str(item.data(Qt.UserRole))
        menu = QMenu(self)
        menu.addAction(QAction(tr("album.open"), menu, triggered=lambda: self.openRequested.emit(album_id)))
        menu.addAction(QAction(tr("album.rename"), menu, triggered=lambda: self.renameRequested.emit(album_id)))
        menu.addAction(QAction(tr("bb.context_menu"), menu, triggered=lambda: self.bbCodeRequested.emit(album_id)))
        menu.addSeparator()
        menu.addAction(QAction(tr("album.forget"), menu, triggered=lambda: self.forgetRequested.emit(album_id)))
        menu.exec(self._list.mapToGlobal(pos))

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        return label
