"""Import existing forum posts as albums — no bot required.
Импорт существующих публикаций как альбомов — без бота.

A webhook cannot list forum threads, so the user pastes jump links (right-click
a post → “Copy Link”). For posts created by this app the album name is recovered
from the starter card (the webhook may read its own messages); other posts get a
placeholder name that can be fixed via “Rename”.
Вебхук не умеет перечислять темы форума, поэтому пользователь вставляет
jump-ссылки (ПКМ по посту → «Копировать ссылку»). Для постов, созданных этим
приложением, имя восстанавливается из стартовой карточки (вебхук может читать
собственные сообщения); остальные получают имя-заглушку (правится «Переименовать»).
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout,
)

from app.albums import MAX_THREAD_NAME, ThreadImport, parse_import_lines, parse_starter_name
from app.discord_client import DiscordClient, DiscordError, TransientDiscordError
from app.i18n import tr

EXAMPLE_LINES = (
    "https://discord.com/channels/123456789012345678/234567890123456789/345678901234567890\n"
    "https://discord.com/channels/123456789012345678/987654321098765432"
)


class NameResolveWorker(QThread):
    """Recover album names from starter cards (webhook reads its own messages).
    Восстанавливает имена альбомов из стартовых карточек — вне GUI-потока."""

    done = Signal(list, int, int)  # list[ThreadImport], resolved, total_with_link

    def __init__(self, webhook_url: str, refs: list, parent=None) -> None:
        super().__init__(parent)
        self._webhook_url = webhook_url
        self._refs = list(refs)

    def run(self) -> None:  # noqa: D102
        imports: list[ThreadImport] = []
        resolved = 0
        total = sum(1 for ref in self._refs if ref.message_id)
        client = DiscordClient(self._webhook_url) if self._webhook_url else None
        try:
            for ref in self._refs:
                name = ""
                if client is not None and ref.message_id:
                    try:
                        message = client.get_webhook_message(ref.message_id, thread_id=ref.thread_id)
                        name = parse_starter_name(str(message.get("content") or ""))
                    except (DiscordError, TransientDiscordError):
                        name = ""
                if name:
                    resolved += 1
                imports.append(ThreadImport(thread_id=ref.thread_id,
                                            name=name or f"Thread {ref.thread_id}",
                                            guild_id=ref.guild_id))
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 — cleanup must never crash the worker
                    pass
        self.done.emit(imports, resolved, total)


class ImportThreadsDialog(QDialog):
    """Paste links → review table → import. / Вставить ссылки → просмотр → импорт."""

    imported = Signal(list, int, int)  # list[ThreadImport], names_resolved, names_total

    def __init__(self, webhook_url: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("import.title"))
        self.setModal(True)
        self.resize(640, 480)
        self._webhook_url = webhook_url
        self._refs: list = []
        self._worker: NameResolveWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel(tr("import.title"), self)
        title.setObjectName("SectionHeader")
        layout.addWidget(title)
        subtitle = QLabel(tr("import.subtitle"), self)
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self._paste = QPlainTextEdit(self)
        self._paste.setPlaceholderText(EXAMPLE_LINES)
        self._paste.setAccessibleName(tr("import.paste_label"))
        self._paste.setTabChangesFocus(True)
        self._paste.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._paste, stretch=1)

        start_row = QHBoxLayout()
        start_row.setSpacing(8)
        start_label = QLabel(tr("import.start_number_label"), self)
        start_row.addWidget(start_label)
        self._start_number = QLineEdit(self)
        self._start_number.setPlaceholderText("1")
        self._start_number.setMaximumWidth(90)
        self._start_number.setToolTip(tr("import.start_number_hint"))
        self._start_number.setAccessibleName(tr("import.start_number_label"))
        start_row.addWidget(self._start_number)
        start_row.addStretch(1)
        layout.addLayout(start_row)

        self._status = QLabel("", self)
        self._status.setObjectName("Hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        buttons = QDialogButtonBox(self)
        self._ok = QPushButton(tr("import.import_button"), self)
        self._ok.setObjectName("Primary")
        self._ok.setEnabled(False)
        buttons.addButton(self._ok, QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton(QDialogButtonBox.Cancel)
        cancel.setText(tr("common.cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------- helpers
    def _on_text_changed(self) -> None:
        refs, invalid = parse_import_lines(self._paste.toPlainText())
        self._refs = refs
        self._ok.setEnabled(bool(refs))
        parts = [tr("import.detected", count=len(refs))]
        if invalid:
            parts.append(tr("import.invalid", count=len(invalid)))
        self._status.setText("  ".join(parts))

    def _start_number_value(self) -> tuple[int, bool]:
        raw = self._start_number.text().strip()
        if not raw:
            return (1, True)
        if raw.isdigit() and int(raw) >= 1:
            return (int(raw), True)
        return (0, False)

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._ok.setEnabled(False if busy else bool(self._refs))
        self._paste.setEnabled(not busy)
        self._start_number.setEnabled(not busy)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        super().closeEvent(event)

    # ------------------------------------------------------------- actions
    def _accept(self) -> None:
        start_number, ok = self._start_number_value()
        if not ok:
            QMessageBox.information(self, tr("import.title"), tr("import.bad_start_number"))
            return
        refs, _invalid = parse_import_lines(self._paste.toPlainText())
        if not refs:
            QMessageBox.information(self, tr("import.title"), tr("import.need_links"))
            return
        needs_resolve = any(ref.message_id for ref in refs) and bool(self._webhook_url)
        if not needs_resolve:
            imports = [ThreadImport(thread_id=ref.thread_id, name=f"Thread {ref.thread_id}",
                                    last_number=start_number - 1, guild_id=ref.guild_id)
                       for ref in refs]
            self.imported.emit(imports, 0, 0)
            self.accept()
            return
        self._set_busy(True)
        self._worker = NameResolveWorker(self._webhook_url, refs, self)

        def _done(raw_imports: list, resolved: int, total: int) -> None:
            self._set_busy(False)
            imports = [ThreadImport(thread_id=item.thread_id, name=item.name[:MAX_THREAD_NAME],
                                    last_number=start_number - 1, guild_id=item.guild_id)
                       for item in raw_imports]
            if imports:
                self.imported.emit(imports, resolved, total)
            self.accept()

        self._worker.done.connect(_done)
        self._worker.start()
