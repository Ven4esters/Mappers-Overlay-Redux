"""Forum discovery dialog: find «альбомы-публикации» already living on the forum.
Диалог поиска существующих публикаций на форуме.

The webhook can neither list channels nor threads, so the user pastes a bot
token once (never stored). Active and archived public posts are merged, can be
filtered and registered as local albums in one pass.
Вебхук не читает список каналов и тем — токен бота (не сохраняется) вставляется
на один раз. Активные и архивные публичные посты объединяются; можно отфильтровать
и зарегистрировать как локальные альбомы за один проход.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from app.albums import MAX_THREAD_NAME, ThreadImport
from app.forum_discovery import (
    ChannelInfo, ForumDiscoveryError, ThreadCandidate, fetch_thread_next_number,
    get_channel_info, list_forum_threads,
)
from app.i18n import tr


class ForumDiscoveryWorker(QThread):
    """Network off the GUI thread. / Сеть вне GUI-потока."""

    succeeded = Signal(object, list)  # ChannelInfo, list[ThreadCandidate]
    failed = Signal(str)               # i18n key for the error

    def __init__(self, token: str, channel_id: str, parent=None) -> None:
        super().__init__(parent)
        self._token = token
        self._channel_id = channel_id

    def run(self) -> None:  # noqa: D102
        try:
            info = get_channel_info(self._token, self._channel_id)
            threads = list_forum_threads(self._token, self._channel_id)
        except ForumDiscoveryError as exc:
            key = {
                "auth": "discover.err_auth",
                "forbidden": "discover.err_forbidden",
                "not_found": "discover.err_not_found",
                "rate_limited": "discover.err_rate_limited",
                "bad_id": "discover.err_bad_id",
                "transient": "discover.err_network",
            }.get(exc.code, "discover.err_generic")
            self.failed.emit(key)
            return
        self.succeeded.emit(info, threads)


class NumberSniffer(QThread):
    """Guess «Название | N.ext» counters for selected threads off the GUI thread.
    Определяет счётчики выбранных тем вне GUI-потока."""

    finished_imports = Signal(list)  # list[ThreadImport]

    def __init__(self, token: str, candidates: list[ThreadCandidate], parent=None) -> None:
        super().__init__(parent)
        self._token = token
        self._candidates = list(candidates)

    def run(self) -> None:  # noqa: D102
        imports: list[ThreadImport] = []
        for cand in self._candidates:
            try:
                last = max(0, fetch_thread_next_number(self._token, cand.thread_id, limit=10) - 1)
            except Exception:  # noqa: BLE001 — sniffing is best effort
                last = 0
            imports.append(ThreadImport(thread_id=cand.thread_id, name=cand.name, last_number=last))
        self.finished_imports.emit(imports)


class ForumDiscoveryDialog(QDialog):
    """Step 1: paste channel + bot token → list posts; step 2: register selection.
    Шаг 1: ID канала + токен бота → список публикаций; шаг 2: регистрация выбранных."""

    imported = Signal(list)  # list[ThreadImport]

    def __init__(self, webhook_url: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("discover.title"))
        self.setModal(True)
        self.resize(640, 460)
        self._candidate_map: dict[str, ThreadCandidate] = {}
        self._worker: ForumDiscoveryWorker | None = None
        self._sniffer: NumberSniffer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel(tr("discover.title"), self)
        title.setObjectName("SectionHeader")
        layout.addWidget(title)
        subtitle = QLabel(tr("discover.subtitle"), self)
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        form = QHBoxLayout()
        form.setSpacing(8)
        self._channel_id = QLineEdit(self)
        self._channel_id.setPlaceholderText(tr("discover.channel_placeholder"))
        self._channel_id.setText(self._channel_id_from_webhook(webhook_url))
        self._channel_id.setAccessibleName(tr("discover.channel_placeholder"))
        form.addWidget(self._channel_id, stretch=2)
        self._token = QLineEdit(self)
        self._token.setPlaceholderText(tr("discover.token_placeholder"))
        self._token.setEchoMode(QLineEdit.Password)
        self._token.setAccessibleName(tr("discover.token_placeholder"))
        form.addWidget(self._token, stretch=2)
        self._toggle_token = QPushButton("👁", self)
        self._toggle_token.setFixedWidth(40)
        self._toggle_token.setToolTip(tr("discover.toggle_token"))
        self._toggle_token.setObjectName("Ghost")
        self._toggle_token.clicked.connect(self._toggle_token_visibility)
        form.addWidget(self._toggle_token)
        layout.addLayout(form)

        self._find_button = QPushButton(tr("discover.find"), self)
        self._find_button.setObjectName("Primary")
        self._find_button.clicked.connect(self._find)
        layout.addWidget(self._find_button, alignment=Qt.AlignLeft)

        help_label = QLabel(tr("discover.token_help"), self)
        help_label.setObjectName("Hint")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText(tr("discover.filter_placeholder"))
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        self._filter.setEnabled(False)
        layout.addWidget(self._filter)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)  # busy indicator
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(
            [tr("discover.col_name"), tr("discover.col_id"), tr("discover.col_state"), tr("discover.col_messages")])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self._table, stretch=1)

        self._next_number = QLineEdit(self)
        self._next_number.setPlaceholderText(tr("discover.next_number_placeholder"))
        self._next_number.setToolTip(tr("discover.next_number_hint"))
        self._next_number.setVisible(False)
        layout.addWidget(self._next_number)

        buttons = QDialogButtonBox(self)
        self._ok = QPushButton(tr("discover.import_selected"), self)
        self._ok.setObjectName("Primary")
        self._ok.setEnabled(False)
        buttons.addButton(self._ok, QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton(QDialogButtonBox.Cancel)
        cancel.setText(tr("common.cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _channel_id_from_webhook(webhook_url: str) -> str:
        # webhook URLs look like .../webhooks/<id>/<token>; the forum channel
        # id is NOT derivable from them, so this is intentionally a no-op helper
        _ = webhook_url
        return ""

    def _toggle_token_visibility(self) -> None:
        mode = self._token.echoMode()
        self._token.setEchoMode(QLineEdit.Normal if mode == QLineEdit.Password else QLineEdit.Password)

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._find_button.setEnabled(not busy)
        self._channel_id.setEnabled(not busy)
        self._token.setEnabled(not busy)
        self._ok.setEnabled(False if busy else self._table.rowCount() > 0)
        self._table.setEnabled(not busy)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        for worker in (self._worker, self._sniffer):
            if worker is not None and worker.isRunning():
                worker.wait(3000)
        super().closeEvent(event)

    def _find(self) -> None:
        token = self._token.text().strip()
        channel = self._channel_id.text().strip()
        if not token or not channel:
            QMessageBox.information(self, tr("discover.title"), tr("discover.need_inputs"))
            return
        self._set_busy(True)
        self._worker = ForumDiscoveryWorker(token, channel, self)
        self._worker.succeeded.connect(self._on_found)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_failed(self, key: str) -> None:
        self._set_busy(False)
        QMessageBox.warning(self, tr("discover.title"), tr(key))

    def _on_found(self, info: ChannelInfo, threads: list) -> None:
        self._set_busy(False)
        if not info.is_forum:
            answer = QMessageBox.question(
                self, tr("discover.title"),
                tr("discover.not_forum", name=info.name or info.channel_id),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                return
        self._candidate_map = {t.thread_id: t for t in threads}
        self._filter.setEnabled(True)
        self._filter.clear()
        self._apply_filter("")

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        self._table.setRowCount(0)
        for thread_id, cand in sorted(self._candidate_map.items(),
                                      key=lambda pair: pair[0], reverse=True):
            if needle and needle not in cand.name.lower():
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            name_item = QTableWidgetItem(cand.name[:MAX_THREAD_NAME])
            name_item.setData(Qt.UserRole, thread_id)
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem(thread_id))
            state = tr("discover.state_archived") if cand.archived else tr("discover.state_active")
            self._table.setItem(row, 2, QTableWidgetItem(state))
            count = "—" if cand.message_count is None else str(cand.message_count)
            self._table.setItem(row, 3, QTableWidgetItem(count))
        self._next_number.setVisible(self._table.rowCount() > 0)
        self._ok.setEnabled(self._table.rowCount() > 0)

    def selected_thread_ids(self) -> list[str]:
        rows = {index.row() for index in self._table.selectionModel().selectedRows()}
        ids = []
        for row in sorted(rows):
            item = self._table.item(row, 0)
            if item is not None:
                ids.append(str(item.data(Qt.UserRole)))
        return ids

    def _accept(self) -> None:
        ids = self.selected_thread_ids()
        if not ids:
            QMessageBox.information(self, tr("discover.title"), tr("discover.need_selection"))
            return
        raw = self._next_number.text().strip()
        forced_next = int(raw) if raw.isdigit() else 0
        if raw and forced_next <= 0:
            QMessageBox.information(self, tr("discover.title"), tr("discover.bad_next_number"))
            return
        selected = [self._candidate_map[i] for i in ids if i in self._candidate_map]
        if forced_next:
            imports = [ThreadImport(thread_id=c.thread_id, name=c.name,
                                    last_number=forced_next - 1) for c in selected]
            if imports:
                self.imported.emit(imports)
            self.accept()
            return
        token = self._token.text().strip()
        self._set_busy(True)
        self._sniffer = NumberSniffer(token, selected, self)

        def _done(imports: list) -> None:
            self._set_busy(False)
            if imports:
                self.imported.emit(imports)
            self.accept()

        self._sniffer.finished_imports.connect(_done)
        self._sniffer.start()
