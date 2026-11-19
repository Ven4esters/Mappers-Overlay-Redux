"""CatBox viewer — separate window: catbox.moe files + the local shot cache.
Окно CatBox — отдельное окно: файлы на catbox.moe + локальный кэш снимков.

Two tabs:
- «CatBox (catbox.moe)»: remote listing via reqtype=userfiles when a userhash
  is configured in Settings; otherwise the locally-known catbox links from the
  send history (honest fallback). Thumbnails are downloaded lazily.
- «Локальный кэш»: everything in ``cache/shots`` — uploads to CatBox happen
  from here, deduplicated by content hash.
This window is deliberately NOT the session queue — the two must stay
independent (user request).
Вкладки: «CatBox» (список по userhash либо локальные ссылки из истории) и
«Локальный кэш» (всё из cache/shots). Окно никак не связано с очередью.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QProgressBar, QPushButton, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget,
)

from app import cache as cache_store
from app import queue_store
from app.catbox import CatboxError, delete_files
from app.i18n import tr
from app.workers import CatboxFilesWorker, CatboxThumbnailWorker, CatboxUploadWorker

logger = logging.getLogger("screensaver.catbox")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_ICON_SIZE = 150
_GRID_W, _GRID_H = 190, 190


def _file_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1] or url


class CatBoxWindow(QWidget):
    """Modeless viewer window. / Безмодальное окно-обозреватель."""

    def __init__(self, store, history, parent=None) -> None:
        super().__init__(None)  # always an independent top-level window
        self.setWindowTitle(tr("catbox.window_title"))
        self.setMinimumSize(920, 600)
        self.resize(1040, 680)
        self._store = store
        self._history = history
        self._uploads: dict[str, str] = {}      # key -> url (last run)
        self._upload_jobs: dict[str, str] = {}  # key -> filename (last run)
        self._remote_urls: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        self._tabs = QTabWidget(self)
        layout.addWidget(self._tabs)

        self._build_remote_tab()
        self._build_local_tab()
        self._tabs.setCurrentIndex(0)

    # ------------------------------------------------------------ tabs
    def _build_local_tab(self) -> None:
        page = QWidget(self._tabs)
        column = QVBoxLayout(page)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        refresh = QPushButton(tr("catbox.refresh"), page)
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self._refresh_local)
        bar.addWidget(refresh)
        upload = QPushButton(tr("catbox.upload_selected"), page)
        upload.setObjectName("Primary")
        upload.clicked.connect(self._upload_selected_local)
        bar.addWidget(upload)
        bar.addStretch(1)
        column.addLayout(bar)

        self._local_empty = QLabel(tr("catbox.empty_local"), page)
        self._local_empty.setObjectName("Subtitle")
        self._local_empty.setWordWrap(True)
        column.addWidget(self._local_empty)

        self._local_list = QListWidget(page)
        self._local_list.setViewMode(QListWidget.IconMode)
        self._local_list.setIconSize(QPixmap(_ICON_SIZE, 110).size())
        self._local_list.setGridSize(QPixmap(_GRID_W, _GRID_H).size())
        self._local_list.setMovement(QListWidget.Static)
        self._local_list.setResizeMode(QListWidget.Adjust)
        self._local_list.setSpacing(6)
        self._local_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._local_list.setWordWrap(True)
        self._local_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._local_list.customContextMenuRequested.connect(self._local_context_menu)
        column.addWidget(self._local_list, stretch=1)

        self._tabs.addTab(page, tr("catbox.tab_local"))

    def _build_remote_tab(self) -> None:
        page = QWidget(self._tabs)
        column = QVBoxLayout(page)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(8)

        self._remote_banner = QLabel(tr("catbox.hint_remote_userhash"), page)
        self._remote_banner.setObjectName("Hint")
        self._remote_banner.setWordWrap(True)
        column.addWidget(self._remote_banner)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        refresh = QPushButton(tr("catbox.refresh"), page)
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self._refresh_remote)
        bar.addWidget(refresh)
        copy_all = QPushButton(tr("catbox.copy_all"), page)
        copy_all.clicked.connect(self._copy_all_remote)
        bar.addWidget(copy_all)
        bar.addStretch(1)
        column.addLayout(bar)

        self._remote_status = QLabel("", page)
        self._remote_status.setObjectName("Dim")
        column.addWidget(self._remote_status)
        self._remote_progress = QProgressBar(page)
        self._remote_progress.setVisible(False)
        column.addWidget(self._remote_progress)

        self._remote_list = QListWidget(page)
        self._remote_list.setViewMode(QListWidget.IconMode)
        self._remote_list.setIconSize(QPixmap(_ICON_SIZE, 110).size())
        self._remote_list.setGridSize(QPixmap(_GRID_W, _GRID_H).size())
        self._remote_list.setMovement(QListWidget.Static)
        self._remote_list.setResizeMode(QListWidget.Adjust)
        self._remote_list.setSpacing(6)
        self._remote_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._remote_list.setWordWrap(True)
        self._remote_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._remote_list.customContextMenuRequested.connect(self._remote_context_menu)
        column.addWidget(self._remote_list, stretch=1)

        self._tabs.addTab(page, tr("catbox.tab_remote"))

    # -------------------------------------------------------- local cache
    def _known_names(self) -> dict[str, str]:
        """cache_name -> original filename (from the queue index + history)."""
        names: dict[str, str] = {}
        for entry in queue_store.load_entries():
            if entry.get("file") and entry.get("filename"):
                names[str(entry["file"])] = str(entry["filename"])
        try:
            for item in self._history.all():
                for attachment in item.attachments:
                    path = getattr(attachment, "local_path", "") or ""
                    if path and getattr(attachment, "filename", ""):
                        names[Path(path).name] = attachment.filename
        except Exception:  # noqa: BLE001 — a broken history must not blank the tab
            logger.exception("could not read history for cache file names")
        return names

    def _refresh_local(self) -> None:
        self._local_list.clear()
        root = cache_store.cache_root()
        known = self._known_names()
        files = []
        if root.is_dir():
            for path in root.iterdir():
                if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
                    try:
                        files.append((path.stat().st_mtime, path))
                    except OSError:
                        continue
        files.sort(reverse=True)
        for _mtime, path in files[:300]:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            pixmap = pixmap.scaled(_ICON_SIZE, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label = known.get(path.name, path.name)
            item = QListWidgetItem(QIcon(pixmap), label)
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(f"{label}\n{path}")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self._local_list.addItem(item)
        self._local_empty.setVisible(self._local_list.count() == 0)
        logger.info("local cache listing: %d image(s)", self._local_list.count())

    def _local_context_menu(self, pos) -> None:
        item = self._local_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self._local_list)
        open_action = menu.addAction(tr("catbox.open_file"))
        upload_action = menu.addAction(tr("catbox.upload_selected"))
        chosen = menu.exec(self._local_list.mapToGlobal(pos))
        path = Path(str(item.data(Qt.UserRole)))
        if chosen is open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif chosen is upload_action:
            self._start_upload([(path.stem, path.name, str(path))])

    def _upload_selected_local(self) -> None:
        jobs = []
        for item in self._local_list.selectedItems():
            path = Path(str(item.data(Qt.UserRole)))
            jobs.append((path.stem, path.name, str(path)))
        self._start_upload(jobs)

    # ---------------------------------------------------------- remote list
    def _known_remote_links(self) -> list[tuple[str, str]]:
        """(url, filename) pairs uploaded in past BB-code exports. / Ссылки из истории."""
        seen: dict[str, str] = {}
        try:
            for item in self._history.all():
                for attachment in item.attachments:
                    url = getattr(attachment, "catbox_url", "") or ""
                    if url and url not in seen:
                        seen[url] = attachment.filename or url
        except Exception:  # noqa: BLE001
            logger.exception("could not read history for catbox links")
        return list(seen.items())

    def _refresh_remote(self) -> None:
        self._remote_list.clear()
        userhash = self._store.settings.catbox_userhash.strip()
        if userhash:
            self._remote_progress.setRange(0, 0)
            self._remote_progress.setVisible(True)
            self._remote_status.setText(tr("catbox.loading"))
            self._list_worker = CatboxFilesWorker(userhash, parent=self)
            self._list_worker.done.connect(self._on_remote_urls)
            self._list_worker.failed.connect(self._on_remote_error)
            self._list_worker.start()
            return
        known = self._known_remote_links()
        self._set_remote_entries(known)
        self._remote_status.setText(
            tr("catbox.empty_remote_local") if not known else "")

    def _on_remote_urls(self, urls: list) -> None:
        self._remote_progress.setVisible(False)
        self._set_remote_entries([(url, _file_name(url)) for url in urls])
        self._remote_status.setText(
            tr("catbox.empty_remote_userhash") if not urls else "")

    def _on_remote_error(self, message: str) -> None:
        self._remote_progress.setVisible(False)
        self._remote_status.setText(tr("catbox.error_load", error=message[:200]))

    def _set_remote_entries(self, entries: list[tuple[str, str]]) -> None:
        self._remote_urls = [url for url, _name in entries]
        for url, name in entries:
            item = QListWidgetItem(QIcon(), name)
            item.setData(Qt.UserRole, url)
            item.setToolTip(url)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self._remote_list.addItem(item)
        if entries:
            self._thumbs = CatboxThumbnailWorker(self._remote_urls, parent=self)
            self._thumbs.itemReady.connect(self._on_thumbnail)
            self._thumbs.start()

    def _on_thumbnail(self, url: str, data: bytes) -> None:
        image = QImage.fromData(data)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            _ICON_SIZE, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        for index in range(self._remote_list.count()):
            item = self._remote_list.item(index)
            if item.data(Qt.UserRole) == url:
                item.setIcon(QIcon(pixmap))
                break

    def _copy_all_remote(self) -> None:
        if not self._remote_urls:
            return
        QApplication.clipboard().setText("\n".join(self._remote_urls))
        self._remote_status.setText(tr("catbox.copied"))

    def _remote_context_menu(self, pos) -> None:
        item = self._remote_list.itemAt(pos)
        if item is None:
            return
        url = str(item.data(Qt.UserRole))
        selected = self._remote_list.selectedItems() or [item]
        menu = QMenu(self._remote_list)
        copy_action = menu.addAction(tr("catbox.copy_link"))
        open_action = menu.addAction(tr("catbox.open_file"))
        userhash = self._store.settings.catbox_userhash.strip()
        delete_action = menu.addAction(tr("catbox.delete")) if userhash else None
        chosen = menu.exec(self._remote_list.mapToGlobal(pos))
        if chosen is copy_action:
            QApplication.clipboard().setText("\n".join(str(i.data(Qt.UserRole)) for i in selected))
        elif chosen is open_action:
            QDesktopServices.openUrl(QUrl(url))
        elif delete_action is not None and chosen is delete_action:
            self._delete_remote(selected)

    def _delete_remote(self, items) -> None:
        userhash = self._store.settings.catbox_userhash.strip()
        names = [_file_name(str(i.data(Qt.UserRole))) for i in items]
        answer = QMessageBox.question(
            self, tr("catbox.delete"), tr("catbox.delete_confirm", count=len(names)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            response = delete_files(userhash, names)
        except CatboxError as exc:
            QMessageBox.warning(self, tr("catbox.delete"), str(exc))
            return
        self._remote_status.setText(tr("catbox.delete_done", response=response[:160] or "?"))
        self._refresh_remote()

    # ------------------------------------------------------------- uploads
    def upload_shots(self, shots) -> None:
        """Upload queue ShotItems (duck-typed) — called by the main window."""
        jobs = []
        for shot in shots:
            cache_name = getattr(shot, "cache_name", "")
            if cache_name:
                path = queue_store.shot_path(cache_name)
                if path.is_file():
                    jobs.append((shot.id, shot.filename, str(path)))
        self._start_upload(jobs)

    def _start_upload(self, jobs: list[tuple[str, str, str]]) -> None:
        if not jobs:
            self._remote_status.setText(tr("catbox.empty_local"))
            self._tabs.setCurrentIndex(0)
            return
        self._tabs.setCurrentIndex(1)
        self._uploads = {}
        self._upload_jobs = {key: filename for key, filename, _path in jobs}
        self._remote_progress.setRange(0, len(jobs))
        self._remote_progress.setValue(0)
        self._remote_progress.setVisible(True)
        self._remote_status.setText(tr("catbox.local_uploading"))
        logger.info("catbox upload started: %d file(s)", len(jobs))
        self._upload_worker = CatboxUploadWorker(
            jobs, userhash=self._store.settings.catbox_userhash.strip(), parent=self)
        self._upload_worker.progress.connect(self._on_upload_progress)
        self._upload_worker.done.connect(self._on_upload_done)
        self._upload_worker.start()

    def _on_upload_progress(self, done: int, total: int) -> None:
        self._remote_progress.setValue(done)
        self._remote_status.setText(tr("catbox.progress", done=done, total=total))

    def _on_upload_done(self, summary) -> None:
        self._remote_progress.setVisible(False)
        self._uploads = dict(summary.urls)
        total = len(self._upload_jobs)
        self._remote_status.setText(tr("catbox.upload_done", done=len(self._uploads), total=total))
        logger.info("catbox upload finished: %d/%d (errors: %d)",
                    len(self._uploads), total, len(summary.errors or {}))
        self._persist_catbox_urls(self._uploads)
        if self._uploads:
            links = "\n".join(self._uploads[key] for key in self._upload_jobs
                              if key in self._uploads)
            answer = QMessageBox.question(
                self, tr("catbox.window_title"), tr("catbox.upload_done",
                                                    done=len(self._uploads), total=total)
                + f"\n\n{links}\n\n" + tr("catbox.copy_all") + "?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                QApplication.clipboard().setText(links)
        if summary.errors:
            detail = next(iter(summary.errors.values()))
            QMessageBox.warning(self, tr("catbox.window_title"), str(detail)[:300])
        self._refresh_local()
        # after an upload the remote listing may know about the new files
        if self._store.settings.catbox_userhash.strip():
            self._refresh_remote()

    def _persist_catbox_urls(self, urls: dict[str, str]) -> None:
        if not urls:
            return
        by_filename = {self._upload_jobs.get(key, key): url for key, url in urls.items()}
        try:
            items = self._history.all()
        except Exception:  # noqa: BLE001
            logger.exception("could not read history to persist catbox links")
            return
        changed_items = 0
        for item in items:
            changed = False
            for attachment in item.attachments:
                url = by_filename.get(attachment.filename)
                if url and attachment.catbox_url != url:
                    attachment.catbox_url = url
                    changed = True
            if changed:
                try:
                    self._history.update_item(item.id, attachments=item.attachments)
                    changed_items += 1
                except Exception:  # noqa: BLE001
                    logger.exception("could not persist catbox link(s) for item %s", item.id)
        if changed_items:
            logger.info("persisted catbox links into history for %d item(s)", changed_items)
