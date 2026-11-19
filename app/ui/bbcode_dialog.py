"""BB-code export dialog (XenForo). / Диалог экспорта BB-кода (XenForo).

Sources of media links: Discord CDN (default, ~24h) or catbox.moe (permanent,
uploaded from the local cache on demand).
Источники ссылок: CDN Discord (по умолчанию, ~24 ч) или catbox.moe
(постоянные, догружаются из локального кэша по требованию).
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from app.bbcode import BBSection, build_bbcode
from app.i18n import tr
from app.models import Attachment
from app.store import ConfigStore, HistoryStore
from app.workers import CatboxUploadWorker

_KEY_SEP = "::"


def _attachment_key(item_id: str, attachment: Attachment) -> str:
    return f"{item_id}{_KEY_SEP}{attachment.filename}"


def _split_key(key: str) -> tuple[str, str]:
    item_id, _, filename = key.partition(_KEY_SEP)
    return item_id, filename


class BBCodeDialog(QDialog):
    """Export one album as a XenForo BB-code post. / Экспорт альбома в BB-код."""

    def __init__(self, store: ConfigStore, history: HistoryStore, album, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("bb.title", album=album.name))
        self.resize(780, 680)
        self._store = store
        self._history = history
        self._album = album
        self._worker: CatboxUploadWorker | None = None
        self._items = history.items_for_album(album.id)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self._summary = QLabel(self)
        self._summary.setObjectName("Dim")
        root.addWidget(self._summary)

        source_box = QGroupBox(tr("bb.source"), self)
        source_layout = QVBoxLayout(source_box)
        self._source_discord = QRadioButton(tr("bb.source_discord"), source_box)
        self._source_discord.setChecked(True)
        self._source_discord.toggled.connect(self._on_source_changed)
        self._source_catbox = QRadioButton(tr("bb.source_catbox"), source_box)
        source_layout.addWidget(self._source_discord)
        source_layout.addWidget(self._source_catbox)
        source_note = QLabel(tr("bb.source_note"), source_box)
        source_note.setObjectName("Dim")
        source_note.setWordWrap(True)
        source_layout.addWidget(source_note)
        root.addWidget(source_box)

        tag_row = QHBoxLayout()
        tag_label = QLabel(tr("bb.media_tag"), self)
        tag_row.addWidget(tag_label)
        self._tag = QComboBox(self)
        self._tag.addItem("IMG", "IMG")
        self._tag.addItem("MEDIA", "MEDIA")
        self._tag.addItem("CUSTOM", "CUSTOM")
        index = self._tag.findData(store.settings.bb_media_tag)
        self._tag.setCurrentIndex(index if index >= 0 else 0)
        self._tag.currentIndexChanged.connect(self._on_tag_changed)
        tag_row.addWidget(self._tag)
        self._custom_tag = QLineEdit(self)
        self._custom_tag.setPlaceholderText("MYTAG")
        self._custom_tag.setText(store.settings.bb_custom_media_tag)
        self._custom_tag.textChanged.connect(self._on_tag_changed)
        tag_row.addWidget(self._custom_tag, stretch=1)
        root.addLayout(tag_row)
        self._sync_custom_tag_enabled()

        self._upload_status = QLabel(self)
        self._upload_status.setObjectName("Dim")
        self._upload_status.hide()
        root.addWidget(self._upload_status)
        self._progress = QProgressBar(self)
        self._progress.hide()
        root.addWidget(self._progress)

        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(9)
        self._output.setFont(mono)
        root.addWidget(self._output, stretch=1)

        self._warning = QLabel(self)
        self._warning.setObjectName("Dim")
        self._warning.setWordWrap(True)
        self._warning.hide()
        root.addWidget(self._warning)

        actions = QHBoxLayout()
        self._copy_button = QPushButton(tr("bb.copy"), self)
        self._copy_button.clicked.connect(self._copy)
        actions.addWidget(self._copy_button)
        self._save_button = QPushButton(tr("bb.save"), self)
        self._save_button.clicked.connect(self._save)
        actions.addWidget(self._save_button)
        actions.addStretch(1)
        close_buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        close_buttons.rejected.connect(self.accept)
        actions.addWidget(close_buttons)
        root.addLayout(actions)

        self._refresh_summary()
        self._regenerate()

    # ------------------------------------------------------------ export
    def _refresh_summary(self) -> None:
        shots = sum(len(item.attachments) for item in self._items)
        self._summary.setText(
            tr("bb.summary", album=self._album.name, sections=len(self._items), shots=shots))

    def _current_links(self) -> list[list[str]]:
        """Per-item resolved links (parallel to self._items); missing ones become None."""
        source = "catbox" if self._source_catbox.isChecked() else "discord"
        resolved: list[list[str | None]] = []
        for item in self._items:
            links: list[str | None] = []
            for attachment in item.attachments:
                if source == "discord":
                    links.append(attachment.url or None)
                elif attachment.catbox_url:
                    links.append(attachment.catbox_url)
                elif attachment.local_path and Path(attachment.local_path).exists():
                    links.append(None)  # uploadable, not uploaded yet
                else:
                    links.append("")    # unrecoverable for catbox
            resolved.append(links)
        return resolved  # type: ignore[return-value]

    def _sections_from_links(self, links: list[list[str | None]]) -> tuple[list[BBSection], int]:
        sections: list[BBSection] = []
        missing = 0
        for item, item_links in zip(self._items, links):
            good = [link for link in item_links if link]
            missing += sum(1 for link in item_links if not link)
            if good:
                sections.append(BBSection(name=item.section, links=good))
        return sections, missing

    def _pending_uploads(self, links: list[list[str | None]]) -> list[tuple[str, str, str]]:
        pending: list[tuple[str, str, str]] = []
        for item, item_links in zip(self._items, links):
            for attachment, link in zip(item.attachments, item_links):
                if link is None and attachment.local_path:
                    pending.append((_attachment_key(item.id, attachment),
                                    attachment.filename, attachment.local_path))
        return pending

    def _regenerate(self) -> None:
        if self._worker is not None:
            return  # an upload run is in flight; it will re-trigger when done
        links = self._current_links()
        if self._source_catbox.isChecked():
            pending = self._pending_uploads(links)
            if pending:
                self._start_uploads(pending)
                return
        sections, missing = self._sections_from_links(links)
        title = self._album.name
        text = build_bbcode(title, sections,
                            heading_template=self._store.settings.bb_heading_template,
                            media_tag=str(self._tag.currentData()),
                            custom_media_tag=self._custom_tag.text())
        if not sections:
            text = tr("bb.empty")
        self._output.setPlainText(text)
        if missing and self._source_catbox.isChecked():
            self._warning.setText(tr("bb.missing_catbox", missing=missing))
            self._warning.show()
        else:
            self._warning.hide()
        has_content = bool(sections)
        self._copy_button.setEnabled(has_content)
        self._save_button.setEnabled(has_content)

    # ------------------------------------------------------------ uploads
    def _start_uploads(self, pending: list[tuple[str, str, str]]) -> None:
        self._progress.setRange(0, len(pending))
        self._progress.setValue(0)
        self._progress.show()
        self._upload_status.setText(tr("bb.uploading", total=len(pending)))
        self._upload_status.show()
        self._set_controls_enabled(False)
        self._worker = CatboxUploadWorker(pending, parent=self)
        self._worker.progress.connect(lambda done, total: self._progress.setValue(done))
        self._worker.done.connect(self._on_uploads_done)
        self._worker.start()

    def _on_uploads_done(self, summary) -> None:
        self._worker = None
        self._progress.hide()
        self._upload_status.hide()
        self._set_controls_enabled(True)
        if summary.urls:
            self._persist_catbox_urls(summary.urls)
        if summary.status == "failed" and summary.errors:
            detail = next(iter(summary.errors.values()))
            QMessageBox.warning(self, tr("bb.title", album=self._album.name),
                                tr("bb.catbox_failed", error=detail))
        elif summary.errors:
            self._warning.setText(tr("bb.catbox_partial", errors=len(summary.errors)))
            self._warning.show()
        # reload items to pick up persisted catbox urls
        self._items = self._history.items_for_album(self._album.id)
        self._regenerate()

    def _persist_catbox_urls(self, urls: dict[str, str]) -> None:
        by_item: dict[str, dict[str, str]] = {}
        for key, url in urls.items():
            item_id, filename = _split_key(key)
            by_item.setdefault(item_id, {})[filename] = url
        for item in self._items:
            updates = by_item.get(item.id)
            if not updates:
                continue
            changed = False
            for attachment in item.attachments:
                url = updates.get(attachment.filename)
                if url and attachment.catbox_url != url:
                    attachment.catbox_url = url
                    changed = True
            if changed:
                self._history.update_item(item.id, attachments=item.attachments)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self._source_discord, self._source_catbox, self._tag,
                       self._custom_tag, self._copy_button, self._save_button):
            widget.setEnabled(enabled)
        if enabled:
            self._sync_custom_tag_enabled()
        else:
            self._custom_tag.setEnabled(False)

    # -------------------------------------------------------------- events
    def _on_source_changed(self, *_args) -> None:
        self._regenerate()

    def _on_tag_changed(self, *_args) -> None:
        self._store.settings.bb_media_tag = str(self._tag.currentData())
        self._store.settings.bb_custom_media_tag = self._custom_tag.text().strip()
        self._store.save()
        self._sync_custom_tag_enabled()
        self._regenerate()

    def _sync_custom_tag_enabled(self) -> None:
        custom = str(self._tag.currentData()) == "CUSTOM"
        self._custom_tag.setEnabled(custom)

    def _copy(self) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self._output.toPlainText())
        self._copy_button.setText(tr("bb.copied"))

    def _save(self) -> None:
        safe = re.sub(r'[\\/:*?"<>|]+', "_", self._album.name).strip() or "album"
        target, _filter = QFileDialog.getSaveFileName(
            self, tr("bb.save"), f"{safe}.bbcode.txt", "Text (*.txt);;All files (*)")
        if not target:
            return
        try:
            Path(target).write_text(self._output.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, tr("bb.save"), str(exc))

    def done(self, result: int) -> None:
        worker = self._worker
        if worker is not None:
            try:
                worker.done.disconnect(self._on_uploads_done)
            except (TypeError, RuntimeError):
                pass
            worker.abort()
            worker.wait(2000)
            self._worker = None
        super().done(result)
