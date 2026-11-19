"""Main window (module 6: full send flow). / Главное окно (модуль 6: отправка)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QInputDialog, QMainWindow, QMessageBox,
    QStatusBar, QVBoxLayout, QWidget,
)

from app import cache as cache_store
from app.cache import mime_for_suffix
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
from app.ui.bbcode_dialog import BBCodeDialog
from app.ui.capture_overlay import CaptureOverlay
from app.ui.hotkey_qt import build_shortcut_sequence

logger = logging.getLogger("screensaver.ui")
from app.ui.import_threads_dialog import ImportThreadsDialog
from app.ui.queue_panel import QueuePanel, ShotItem
from app.ui.region_overlay import RegionOverlay
from app.ui.send_panel import SendPanel
from app.ui.settings_dialog import SettingsDialog
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
        self._capture_overlay: CaptureOverlay | None = None
        self._capture_shortcut: QShortcut | None = None
        self._shot_seq = 0
        self._pending_cache_paths: list[str] = []

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
        self.sidebar.importRequested.connect(self._import_albums)
        self.sidebar.openRequested.connect(self._open_album)
        self.sidebar.renameRequested.connect(self._rename_album)
        self.sidebar.forgetRequested.connect(self._forget_album)
        self.sidebar.bbCodeRequested.connect(self._open_bbcode)
        self.sidebar.settingsRequested.connect(self._open_settings)
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
        self._apply_sending_defaults()

    def _apply_sending_defaults(self) -> None:
        settings = self.store.settings
        self.panel.set_send_mode(settings.send_mode if settings.send_mode in ("single", "separate") else "single")
        self.panel.set_style(settings.section_style if settings.section_style in ("text", "embed") else "text")
        self.panel.set_duplicate_caption(settings.duplicate_caption)

    def _install_hotkeys(self) -> None:
        self._hotkeys = HotkeyManager(self)
        self._hotkeys.actionRequested.connect(self._on_hotkey)
        combo = self.store.settings.capture_hotkey
        failed = self._hotkeys.install(QApplication.instance(), combo)
        if failed:
            logger.warning("global hotkey(s) refused by Windows: %s", ", ".join(failed))
            self._status.showMessage(
                tr("capture.hotkey_unavailable", combos=", ".join(failed)), 6000)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=lambda: self._capture("fullscreen"))
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=lambda: self._capture("region"))
        self._capture_shortcut = None
        self._bind_capture_shortcut(combo)

    def _bind_capture_shortcut(self, combo: str) -> None:
        if self._capture_shortcut is not None:
            self._capture_shortcut.setEnabled(False)
            self._capture_shortcut.deleteLater()
            self._capture_shortcut = None
        sequence = build_shortcut_sequence(combo)
        if sequence is None:
            return
        self._capture_shortcut = QShortcut(sequence, self, activated=self._show_capture_overlay)

    def _on_recorder_armed(self, armed: bool) -> None:
        if armed:
            self._hotkeys.suspend()
        else:
            self._resume_global_hotkeys()

    def _resume_global_hotkeys(self) -> None:
        refused = self._hotkeys.resume()
        if refused:
            self._status.showMessage(
                tr("capture.hotkey_unavailable", combos=", ".join(refused)), 6000)

    def _on_capture_hotkey_changed(self, combo: str) -> None:
        ok = self._hotkeys.rebind_capture(combo)
        if ok:
            self._bind_capture_shortcut(combo)
            self._status.showMessage(tr("settings.hotkey_applied", combo=combo), 4000)
        else:
            self._status.showMessage(tr("settings.hotkey_rebind_failed", combo=combo), 6000)

    def _on_hotkey(self, which: str) -> None:
        if which == "overlay":
            self._show_capture_overlay()
            return
        self._capture("fullscreen" if which == "fullscreen" else "region")

    def _show_capture_overlay(self) -> None:
        logger.info("capture overlay requested (last mode: %s)", self.store.settings.last_capture_mode)
        last = self.store.settings.last_capture_mode
        overlay = CaptureOverlay(last, self)
        overlay.modeChosen.connect(self._on_overlay_mode)
        overlay.cancelled.connect(lambda: self._status.showMessage(tr("capture.cancelled"), 2000))
        overlay.destroyed.connect(lambda: setattr(self, "_capture_overlay", None))
        self._capture_overlay = overlay
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()

    def _on_overlay_mode(self, mode: str) -> None:
        self.store.settings.last_capture_mode = mode
        self.store.save()
        self._capture(mode)

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
        if which in ("fullscreen", "window", "region") and self.store.settings.last_capture_mode != which:
            self.store.settings.last_capture_mode = which
            self.store.save()
        try:
            if which == "fullscreen":
                self._add_image(capture_fullscreen())
            elif which == "window":
                self._add_image(capture_active_window())
            elif which == "region":
                self._overlay = RegionOverlay()
                self._overlay.regionSelected.connect(self._region_captured)
                self._overlay.cancelled.connect(self._region_cancelled)
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

    def _region_cancelled(self) -> None:
        self._overlay = None
        self._status.showMessage(tr("capture.cancelled"), 3000)

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
            shots.append(ShotItem.create(Path(path).name, data, mime_for_suffix(Path(path).suffix)))
        if shots:
            self.queue.add(shots)

    # ------------------------------------------------------------- albums
    def _create_album(self) -> None:
        profile = self.store.active_profile()
        if profile is None:
            answer = QMessageBox.question(
                self, tr("nav.settings"), tr("common.need_profile"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self._open_settings()
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

    def _import_albums(self) -> None:
        profile = self.store.active_profile()
        if profile is None:
            QMessageBox.information(self, tr("settings.title"), tr("settings.no_profiles"))
            return
        dialog = ImportThreadsDialog(webhook_url=profile.webhook_url, parent=self)
        dialog.imported.connect(self._import_links)
        dialog.exec()
        self._reload_albums()

    def _import_links(self, items: list, resolved: int, total: int) -> None:
        profile = self.store.active_profile()
        if profile is None:
            return
        created, skipped = self.service.import_threads(profile, items)
        logger.info("forum link import: attached=%d duplicates=%d", len(created), skipped)
        if not created:
            QMessageBox.information(self, tr("import.title"), tr("import.all_skipped"))
            return
        text = tr("import.imported", count=len(created))
        if skipped:
            text += " " + tr("import.skipped_suffix", count=skipped)
        if total:
            text += " " + tr("import.resolved_suffix", resolved=resolved, total=total)
        QMessageBox.information(self, tr("import.title"), text)
        self._reload_albums(select_id=created[0].id)

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

    def _open_bbcode(self, album_id: str) -> None:
        album = self.store.get_album(album_id)
        if album is None:
            return
        dialog = BBCodeDialog(self.store, self.history, album, self)
        dialog.exec()

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
        self._pending_cache_paths = []
        for file in files:
            local_path = ""
            if settings.keep_local_cache:
                try:
                    local_path = str(cache_store.save_shot(file.data, file.filename))
                except OSError:
                    local_path = ""
            self._pending_cache_paths.append(local_path)

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
            cache_paths = self._pending_cache_paths
            flat_index = 0
            for result in summary.results:
                attachments = []
                for a in result.attachments:
                    local = cache_paths[flat_index] if flat_index < len(cache_paths) else ""
                    attachments.append(Attachment(filename=a.get("filename", ""),
                                                  url=a.get("url", ""),
                                                  local_path=local))
                    flat_index += 1
                self.history.append(HistoryItem(
                    id=result.message_id or f"{utcnow_iso()}-{result.channel_id}",
                    album_id=album_id,
                    album_name=album.name if album else "",
                    section=name,
                    description=self.panel.description(),
                    message_url=result.message_url,
                    status="ok",
                    attachments=attachments,
                ))
            self._pending_cache_paths = []
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
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.store, self)
        dialog.profilesChanged.connect(self._refresh_profiles)
        dialog.sendingDefaultsChanged.connect(self._apply_sending_defaults)
        dialog.configImported.connect(self._on_config_imported)
        dialog.captureHotkeyChanged.connect(self._on_capture_hotkey_changed)
        dialog.recorderArmed.connect(self._on_recorder_armed)
        try:
            dialog.exec()
        finally:
            # never leave hotkeys suspended if the dialog goes away mid-record
            self._resume_global_hotkeys()

    def _on_config_imported(self) -> None:
        self.store.reload()
        self._apply_sending_defaults()
        self._refresh_profiles()
        combo = self.store.settings.capture_hotkey
        self._hotkeys.rebind_capture(combo)
        self._bind_capture_shortcut(combo)
        self._status.showMessage(tr("settings.import_reloaded"), 4000)

    def _history_stub(self) -> None:
        QMessageBox.information(self, tr("nav.history"), tr("common.module_pending"))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None:
            self._worker.abort()
            self._worker.wait(3000)
        self._hotkeys.shutdown()
        self.store.save()
        super().closeEvent(event)
