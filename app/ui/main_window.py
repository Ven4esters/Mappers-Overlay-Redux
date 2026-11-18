"""Main window (module 6: full send flow). / Главное окно (модуль 6: отправка)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QInputDialog, QMainWindow, QMessageBox,
    QStatusBar, QVBoxLayout, QWidget,
)

from app import __version__
from app import cache as cache_store
from app.albums import AlbumError, AlbumsService, format_shot_filename
from app.capture import (
    CaptureError, Region, UnsupportedPlatformError, capture_active_window,
    capture_fullscreen, capture_region, image_to_bytes,
)
from app.discord_client import DiscordError, UploadedFile
from app.hotkeys import HotkeyManager
from app.i18n import tr
from app.models import Attachment, HistoryItem, utcnow_iso
from app.store import ConfigStore, HistoryStore
from app.ui.album_sidebar import AlbumSidebar
from app.ui.queue_panel import QueuePanel, ShotItem
from app.ui.region_overlay import RegionOverlay
from app.ui.send_panel import SendPanel
from app.workers import SendWorker


class MainWindow(QMainWindow):
    """Three-pane layout: album sidebar | capture queue | send panel.
    Три панели: сайдбар альбомов | очередь | панель отправки."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("app.window_title"))
        self.resize(1300, 780)
        self.setMinimumSize(1120, 660)

        self.store = ConfigStore()
        self.history = HistoryStore()
        self.service = AlbumsService(self.store)
        self._worker: SendWorker | None = None
        self._overlay: RegionOverlay | None = None
        self._shot_seq = 0

        self._build_ui()
        self._restore_settings()
        self._install_hotkeys()
        self._refresh_profiles()

    # -------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = AlbumSidebar(self.store, self)
        self.sidebar.profileChanged.connect(self._on_profile_changed)
        self.sidebar.albumSelected.connect(self._on_album_selected)
        self.sidebar.createRequested.connect(self._create_album)
        self.sidebar.attachRequested.connect(self._attach_album)
        self.sidebar.openRequested.connect(self._open_album)
        self.sidebar.renameRequested.connect(self._rename_album)
        self.sidebar.forgetRequested.connect(self._forget_album)
        self.sidebar.settingsRequested.connect(self._settings_stub)
        self.sidebar.historyRequested.connect(self._history_stub)
        layout.addWidget(self.sidebar)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(18, 16, 18, 16)
        self.queue = QueuePanel(center)
        self.queue.captureRequested.connect(self._capture)
        self.queue.openFilesRequested.connect(self._open_files)
        self.queue.changed.connect(self._sync_can_send)
        center_layout.addWidget(self.queue)
        layout.addWidget(center, stretch=1)

        self.panel = SendPanel(self)
        self.panel.sendRequested.connect(self._send)
        self.panel.cancelRequested.connect(self._cancel_send)
        self.panel.resetCounterRequested.connect(self._reset_counter)
        layout.addWidget(self.panel)

        self._status = QStatusBar(self)
        self.setStatusBar(self._status)
        self._status.showMessage(tr("common.ready"))

    def _restore_settings(self) -> None:
        settings = self.store.settings
        self.panel.set_send_mode(settings.send_mode if settings.send_mode in ("single", "separate") else "single")
        self.panel.set_style(settings.section_style if settings.section_style in ("text", "embed") else "text")
        self.panel.set_duplicate_caption(settings.duplicate_caption)

    def _install_hotkeys(self) -> None:
        self._hotkeys = HotkeyManager(self)
        self._hotkeys.actionRequested.connect(
            lambda which: self._capture("fullscreen" if which == "fullscreen" else "region"))
        self._hotkeys.install(QApplication.instance())
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=lambda: self._capture("fullscreen"))
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=lambda: self._capture("region"))

    # ------------------------------------------------------------- sidebar
    def _refresh_profiles(self) -> None:
        profiles = self.store.profiles
        settings = self.store.settings
        if profiles and settings.active_profile_id not in {p.id for p in profiles}:
            settings.active_profile_id = profiles[0].id
            self.store.save()
        self.sidebar.refresh_profiles(profiles, settings.active_profile_id)
        if profiles:
            self._on_profile_changed(settings.active_profile_id)
        else:
            self._reload_albums()

    def _on_profile_changed(self, profile_id: str) -> None:
        if not profile_id:
            return
        self.store.settings.active_profile_id = profile_id
        self.store.save()
        self._reload_albums()

    def _reload_albums(self, select_id: str = "") -> None:
        profile_id = self.store.settings.active_profile_id
        albums = self.store.albums_for(profile_id) if profile_id else []
        self.sidebar.refresh_albums(albums)
        current = select_id or self.sidebar.selected_album_id() or (albums[0].id if albums else "")
        if current:
            self.sidebar.select_album(current)
        self._sync_panel_album(current)

    def _current_album(self):
        album_id = self.sidebar.selected_album_id()
        return self.store.get_album(album_id) if album_id else None

    def _on_album_selected(self, album_id: str) -> None:
        self.panel.clear_result()
        self._sync_panel_album(album_id)

    def _sync_panel_album(self, album_id: str) -> None:
        album = self.store.get_album(album_id) if album_id else None
        self.panel.set_album(album.name if album else None,
                             album.next_number if album else 1,
                             album.shots_sent if album else 0)
        self._sync_can_send()

    def _sync_can_send(self) -> None:
        album = self._current_album()
        can = album is not None and bool(self.queue.checked_shots()) and self._worker is None
        self.panel.set_can_send(can)

    # ------------------------------------------------------------- capture
    def _capture(self, which: str) -> None:
        try:
            if which == "fullscreen":
                self._add_image(capture_fullscreen())
            elif which == "window":
                self._add_image(capture_active_window())
            elif which == "region":
                self._overlay = RegionOverlay()
                self._overlay.regionSelected.connect(self._region_captured)
                self._overlay.cancelled.connect(
                    lambda: self._status.showMessage(tr("capture.cancelled"), 3000))
        except UnsupportedPlatformError as exc:
            QMessageBox.warning(self, tr("app.window_title"), str(exc))
        except CaptureError as exc:
            QMessageBox.critical(self, tr("app.window_title"), str(exc))

    def _region_captured(self, rect) -> None:
        dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
        try:
            image = capture_region(Region(rect.x(), rect.y(), rect.width(), rect.height()), dpr=dpr)
        except CaptureError as exc:
            QMessageBox.critical(self, tr("app.window_title"), str(exc))
            return
        self._add_image(image)

    def _add_image(self, image) -> None:
        self._shot_seq += 1
        name = f"shot_{datetime.now():%Y%m%d_%H%M%S}_{self._shot_seq}.png"
        self.queue.add([ShotItem.create(name, image_to_bytes(image, "PNG"), "image/png")])
        self._status.showMessage(tr("common.ready"), 1500)

    def _open_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, tr("queue.add_files"), "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;All files (*.*)")
        shots = []
        for path in paths:
            try:
                data = Path(path).read_bytes()
            except OSError:
                continue
            suffix = Path(path).suffix.lower().lstrip(".") or "png"
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
                    "gif": "image/gif", "bmp": "image/bmp"}.get(suffix, "image/png")
            shots.append(ShotItem.create(Path(path).name, data, mime))
        if shots:
            self.queue.add(shots)

    # ------------------------------------------------------------- albums
    def _create_album(self) -> None:
        profile = self.store.active_profile()
        if profile is None:
            QMessageBox.information(self, tr("nav.settings"), tr("common.module_pending"))
            return
        name, ok = QInputDialog.getText(self, tr("album.create_title"), tr("album.create_label"),
                                         text="")
        if not ok or not name.strip():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            album = self.service.create_album(profile, name)
        except AlbumError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("album.create_failed"), exc.detail or exc.code)
            return
        except DiscordError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("album.create_failed"), self._friendly_error(exc.code))
            return
        QApplication.restoreOverrideCursor()
        self._status.showMessage(tr("album.created", name=album.name), 4000)
        self._reload_albums(select_id=album.id)

    def _attach_album(self) -> None:
        profile = self.store.active_profile()
        if profile is None:
            return
        link, ok = QInputDialog.getText(self, tr("album.attach_title"), tr("album.attach_label"))
        if not ok or not link.strip():
            return
        try:
            album = self.service.attach_by_link(profile, link)
        except AlbumError as exc:
            QMessageBox.warning(self, tr("album.attach_failed"), exc.detail or exc.code)
            return
        self._reload_albums(select_id=album.id)

    def _open_album(self, album_id: str) -> None:
        album = self.store.get_album(album_id)
        if album is None:
            return
        url = (f"https://discord.com/channels/{album.guild_id}/{album.thread_id}"
               if album.guild_id else "https://discord.com/app")
        QDesktopServices.openUrl(QUrl(url))

    def _rename_album(self, album_id: str) -> None:
        album = self.store.get_album(album_id)
        if album is None:
            return
        name, ok = QInputDialog.getText(self, tr("album.rename_title"), tr("album.rename_label"),
                                         text=album.name)
        if not ok or not name.strip():
            return
        self.service.rename_local(album_id, name)
        self._reload_albums(select_id=album_id)

    def _forget_album(self, album_id: str) -> None:
        album = self.store.get_album(album_id)
        if album is None:
            return
        answer = QMessageBox.question(
            self, tr("album.forget"), tr("album.forget_confirm", name=album.name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.service.forget(album_id)
            self._reload_albums()

    def _reset_counter(self) -> None:
        album = self._current_album()
        if album is not None:
            self.store.update_album(album.id, last_number=0)
            self._sync_panel_album(album.id)

    # ---------------------------------------------------------------- send
    def _send(self) -> None:
        album = self._current_album()
        if album is None:
            self.panel.show_error(tr("send.no_album"))
            return
        shots = self.queue.checked_shots()
        if not shots:
            self.panel.show_error(tr("send.no_shots"))
            return
        name = self.panel.section_name()
        if not name:
            self.panel.highlight_name_error()
            self.panel.show_error(tr("send.empty_name"))
            return
        profile = self.store.get_profile(album.profile_id)
        if profile is None:
            return

        settings = self.store.settings
        settings.send_mode = self.panel.send_mode()
        settings.section_style = self.panel.style()
        settings.duplicate_caption = self.panel.duplicate_caption()
        settings.active_profile_id = profile.id
        self.store.save()

        start = album.next_number
        files = [
            UploadedFile(format_shot_filename(name, start + i, shot.ext), shot.data, shot.mime)
            for i, shot in enumerate(shots)
        ]
        if settings.keep_local_cache:
            for file in files:
                try:
                    cache_store.save_shot(file.data, file.filename)
                except OSError:
                    pass

        total = 1 + (len(files) - 1) if settings.send_mode == "separate" else -(-len(files) // 10)
        self._start_worker(album, profile, files, name, total)

    def _start_worker(self, album, profile, files, name, total) -> None:
        self.panel.clear_result()
        self.panel.set_sending(True, total)
        self._sync_can_send()
        self._worker = SendWorker(
            webhook_url=profile.webhook_url, album=album, files=files,
            section_name=name, description=self.panel.description(),
            style=self.panel.style(), send_mode=self.panel.send_mode(),
            duplicate_caption=self.panel.duplicate_caption(),
            username=profile.username_override, avatar_url=profile.avatar_url,
            parent=self)
        self._worker.progress.connect(self.panel.set_progress)
        self._worker.done.connect(lambda summary: self._on_send_done(album.id, name, summary))
        self._worker.start()

    def _cancel_send(self) -> None:
        if self._worker is not None:
            self._worker.abort()
            self._status.showMessage(tr("send.cancel") + " …", 2000)

    def _on_send_done(self, album_id: str, name: str, summary) -> None:
        self.panel.set_sending(False)
        self._worker = None
        album = self.store.get_album(album_id)
        settings = self.store.settings
        delivered_shots = sum(len(r.attachments) for r in summary.results)
        if album is not None and summary.messages:
            # keep the running counter continuous even on partial delivery
            album.register_send(shots=delivered_shots, messages=summary.messages)
            self.store.save()

        if summary.status == "ok":
            for result in summary.results:
                self.history.append(HistoryItem(
                    id=result.message_id or f"{utcnow_iso()}-{result.channel_id}",
                    album_id=album_id,
                    album_name=album.name if album else "",
                    section=name,
                    description=self.panel.description(),
                    message_url=result.message_url,
                    status="ok",
                    attachments=[Attachment(filename=a.get("filename", ""), url=a.get("url", ""))
                                for a in result.attachments],
                ))
            self.queue.clear()
            if settings.clear_fields_after_send:
                self.panel.clear_caption_fields()
            self.panel.show_ok(summary.message_url)
            self._reload_albums(select_id=album_id)
        elif summary.status == "aborted":
            self._record_failure(album_id, name, "aborted", summary.error_message)
            self.panel.show_error(tr("result.aborted"))
            self._reload_albums(select_id=album_id)
        else:
            message = self._friendly_error(summary.error_code) or summary.error_message
            self._record_failure(album_id, name, summary.error_code, message)
            self.panel.show_error(message)
            self._reload_albums(select_id=album_id)
        self._sync_can_send()

    def _record_failure(self, album_id: str, name: str, code: str, message: str) -> None:
        self.history.append(HistoryItem(
            id=f"{utcnow_iso()}-{code}",
            album_id=album_id,
            album_name=(self.store.get_album(album_id).name if self.store.get_album(album_id) else ""),
            section=name,
            description=self.panel.description(),
            status="failed",
            error=f"{code}: {message}",
        ))

    def _friendly_error(self, code: str) -> str:
        return tr({
            "webhook_dead": "error.webhook_dead",
            "too_large": "error.too_large",
            "forum": "error.forum",
            "rate_limited": "error.rate_limited",
            "transient": "error.transient",
            "validation": "error.validation",
            "aborted": "result.aborted",
        }.get(code, "error.unknown"))

    # ---------------------------------------------------------------- misc
    def _settings_stub(self) -> None:
        QMessageBox.information(self, tr("nav.settings"), tr("common.module_pending"))

    def _history_stub(self) -> None:
        QMessageBox.information(self, tr("nav.history"), tr("common.module_pending"))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None:
            self._worker.abort()
            self._worker.wait(3000)
        self._hotkeys.shutdown()
        self.store.save()
        super().closeEvent(event)
