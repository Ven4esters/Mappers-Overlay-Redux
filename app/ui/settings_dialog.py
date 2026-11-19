"""Settings dialog: webhook profiles, sending defaults, app (cache/language/backup).
Диалог настроек: профили вебхуков, параметры отправки, приложение (кэш/язык/бэкап)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from app import cache as cache_store
from app import transfer
from app.discord_client import DiscordClient, DiscordError
from app.i18n import tr
from app.oauth import load_oauth_client
from app.store import ConfigStore
from app.webhook_url import is_webhook_url
from app.workers import ConnectDiscordWorker

_CHANNEL_TYPES = (("forum", "forum"), ("text", "text"))


def _friendly_error(code: str) -> str:
    return tr({
        "webhook_dead": "error.webhook_dead",
        "too_large": "error.too_large",
        "forum": "error.forum",
        "rate_limited": "error.rate_limited",
        "transient": "error.transient",
        "validation": "error.validation",
    }.get(code, "error.unknown"))


class SettingsDialog(QDialog):
    """Modal settings. / Модальные настройки.

    Signals: profilesChanged — the profile set/active changed (main window refreshes);
    sendingDefaultsChanged — sending defaults changed (main window re-applies);
    configImported — everything was replaced from a backup bundle.
    """

    profilesChanged = Signal()
    sendingDefaultsChanged = Signal()
    configImported = Signal()

    def __init__(self, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumSize(720, 560)
        self._store = store
        self._create_mode = False
        self._loading = False
        self._connect_worker: ConnectDiscordWorker | None = None

        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._build_profiles_tab(), tr("settings.tab_profiles"))
        tabs.addTab(self._build_sending_tab(), tr("settings.tab_sending"))
        tabs.addTab(self._build_app_tab(), tr("settings.tab_app"))
        root.addWidget(tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.accept)
        root.addWidget(buttons)

        self._load_profiles()
        self._load_sending()
        self._refresh_cache_stats()

    # ---------------------------------------------------------- profiles tab
    def _build_profiles_tab(self) -> QWidget:
        page = QWidget(self)
        outer = QHBoxLayout(page)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        self._profile_list = QListWidget(page)
        self._profile_list.itemSelectionChanged.connect(self._on_profile_selected)
        left.addWidget(self._profile_list, stretch=1)
        row = QHBoxLayout()
        self._new_button = QPushButton(f"＋ {tr('settings.profile_new')}", page)
        self._new_button.clicked.connect(self._start_create)
        row.addWidget(self._new_button)
        self._connect_button = QPushButton(f"🔗 {tr('settings.connect_discord')}", page)
        self._connect_button.setObjectName("Primary")
        self._connect_button.clicked.connect(self._connect_discord)
        left.addWidget(self._connect_button)
        left.addWidget(self._hint_label(page))
        self._remove_button = QPushButton(tr("settings.profile_remove"), page)
        self._remove_button.setObjectName("Danger")
        self._remove_button.clicked.connect(self._remove_profile)
        row.addWidget(self._remove_button)
        left.addLayout(row)
        self._activate_button = QPushButton(f"★ {tr('settings.profile_activate')}", page)
        self._activate_button.clicked.connect(self._activate_profile)
        left.addWidget(self._activate_button)
        outer.addLayout(left, stretch=2)

        form_host = QWidget(page)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._name = QLineEdit(form_host)
        form.addRow(tr("settings.profile_name"), self._name)

        url_row = QHBoxLayout()
        self._url = QLineEdit(form_host)
        self._url.setEchoMode(QLineEdit.Password)
        self._url.setPlaceholderText("https://discord.com/api/webhooks/…")
        url_row.addWidget(self._url, stretch=1)
        self._show_url = QCheckBox(tr("settings.show_secret"), form_host)
        self._show_url.toggled.connect(
            lambda checked: self._url.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
        url_row.addWidget(self._show_url)
        form.addRow(tr("settings.profile_url"), url_row)

        self._type = QComboBox(form_host)
        for key, label_key in _CHANNEL_TYPES:
            self._type.addItem(tr(f"settings.type_{label_key}"), key)
        form.addRow(tr("settings.profile_type"), self._type)

        self._username = QLineEdit(form_host)
        self._username.setPlaceholderText(tr("settings.profile_username_ph"))
        form.addRow(tr("settings.profile_username"), self._username)

        self._avatar = QLineEdit(form_host)
        self._avatar.setPlaceholderText("https://…/avatar.png")
        form.addRow(tr("settings.profile_avatar"), self._avatar)

        self._test_button = QPushButton(tr("settings.test"), form_host)
        self._test_button.clicked.connect(self._test_webhook)
        form.addRow("", self._test_button)
        self._test_result = QLabel("", form_host)
        self._test_result.setWordWrap(True)
        self._test_result.setObjectName("Dim")
        form.addRow("", self._test_result)

        self._form_error = QLabel("", form_host)
        self._form_error.setWordWrap(True)
        self._form_error.setStyleSheet("color:#F87171;")
        self._form_error.hide()
        form.addRow("", self._form_error)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self._save_button = QPushButton(tr("common.save"), form_host)
        self._save_button.setObjectName("Primary")
        self._save_button.clicked.connect(self._save_profile)
        save_row.addWidget(self._save_button)
        form.addRow("", save_row)

        form.addRow("", QLabel(tr("settings.profile_hint"), form_host))
        outer.addWidget(form_host, stretch=3)
        return page

    def _load_profiles(self, select_id: str = "") -> None:
        self._loading = True
        active_id = self._store.settings.active_profile_id
        current = select_id or self.selected_profile_id()
        self._profile_list.clear()
        for profile in self._store.profiles:
            badge = "★ " if profile.id == active_id else ""
            icon = "🏟" if profile.is_forum else "💬"
            item = QListWidgetItem(f"{badge}{icon}  {profile.name}")
            item.setData(Qt.UserRole, profile.id)
            item.setToolTip(profile.webhook_url if profile.webhook_url else tr("settings.profile_no_url"))
            self._profile_list.addItem(item)
        if current:
            for index in range(self._profile_list.count()):
                if self._profile_list.item(index).data(Qt.UserRole) == current:
                    self._profile_list.setCurrentRow(index)
                    break
        elif self._profile_list.count():
            self._profile_list.setCurrentRow(0)
        self._loading = False
        self._on_profile_selected()

    @staticmethod
    def _hint_label(page: QWidget) -> QLabel:
        hint = QLabel(tr("settings.connect_hint"), page)
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        return hint

    def selected_profile_id(self) -> str:
        item = self._profile_list.currentItem()
        return str(item.data(Qt.UserRole)) if item else ""

    def _on_profile_selected(self) -> None:
        if self._loading:
            return
        if self._create_mode:
            return
        profile = self._store.get_profile(self.selected_profile_id())
        if profile is None:
            self._clear_form()
            return
        self._fill_form(profile)
        self._set_buttons_for_mode(create=False)

    def _fill_form(self, profile) -> None:
        self._name.setText(profile.name)
        self._url.setText(profile.webhook_url)
        index = self._type.findData(profile.channel_type)
        self._type.setCurrentIndex(max(0, index))
        self._username.setText(profile.username_override)
        self._avatar.setText(profile.avatar_url)
        self._test_result.clear()
        self._form_error.hide()

    def _clear_form(self) -> None:
        self._name.clear()
        self._url.clear()
        self._type.setCurrentIndex(0)
        self._username.clear()
        self._avatar.clear()
        self._test_result.clear()
        self._form_error.hide()

    def _set_buttons_for_mode(self, create: bool) -> None:
        self._create_mode = create
        self._save_button.setText(tr("settings.profile_add") if create else tr("common.save"))
        self._remove_button.setEnabled(not create)
        self._activate_button.setEnabled(not create)

    def _start_create(self) -> None:
        self._profile_list.blockSignals(True)
        self._profile_list.clearSelection()
        self._profile_list.blockSignals(False)
        self._clear_form()
        self._set_buttons_for_mode(create=True)
        self._name.setFocus()

    def _save_profile(self) -> None:
        name = self._name.text().strip()
        url = self._url.text().strip()
        if not name:
            self._show_form_error(tr("settings.err_name"))
            return
        if not is_webhook_url(url):
            self._show_form_error(tr("settings.err_url"))
            return
        channel_type = str(self._type.currentData())
        username = self._username.text().strip()
        avatar = self._avatar.text().strip()
        try:
            if self._create_mode:
                profile = self._store.add_profile(name, url, channel_type=channel_type,
                                                  username_override=username, avatar_url=avatar)
            else:
                profile = self._store.update_profile(
                    self.selected_profile_id(), name=name, webhook_url=url,
                    channel_type=channel_type, username_override=username, avatar_url=avatar)
                if profile is None:
                    self._show_form_error(tr("settings.err_missing"))
                    return
        except ValueError as exc:
            self._show_form_error(str(exc))
            return
        self._set_buttons_for_mode(create=False)
        self._load_profiles(select_id=profile.id)
        self.profilesChanged.emit()

    def _remove_profile(self) -> None:
        profile_id = self.selected_profile_id()
        profile = self._store.get_profile(profile_id)
        if profile is None:
            return
        answer = QMessageBox.question(
            self, tr("settings.profile_remove"),
            tr("settings.profile_remove_confirm", name=profile.name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._store.remove_profile(profile_id)
        self._set_buttons_for_mode(create=False)
        self._load_profiles()
        self.profilesChanged.emit()

    def _activate_profile(self) -> None:
        profile_id = self.selected_profile_id()
        if not profile_id:
            return
        self._store.settings.active_profile_id = profile_id
        self._store.save()
        self._load_profiles(select_id=profile_id)
        self.profilesChanged.emit()

    def _test_webhook(self) -> None:
        url = self._url.text().strip()
        if not is_webhook_url(url):
            self._show_form_error(tr("settings.err_url"))
            return
        self._form_error.hide()
        self._test_result.setText(tr("settings.testing"))
        self._test_button.setEnabled(False)
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            client = DiscordClient(url, timeout=8.0)
            try:
                info = client.get_webhook_info()
            finally:
                client.close()
        except DiscordError as exc:
            self._test_result.setText(f"✗ {_friendly_error(exc.code)}")
            self._test_result.setStyleSheet("color:#F87171;")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._test_button.setEnabled(True)
        name = str(info.get("name", "?"))
        channel = str(info.get("channel_id", "?"))
        guild = str(info.get("guild_id", ""))
        detail = f"{name} · #{channel}" + (f" · guild {guild}" if guild else "")
        self._test_result.setText(f"✓ {tr('settings.test_ok')}: {detail}")
        self._test_result.setStyleSheet("color:#34D399;")

    def _connect_discord(self) -> None:
        config, error = load_oauth_client()
        if config is None:
            QMessageBox.information(self, tr("settings.connect_discord"),
                                    f"{tr('settings.connect_setup')}\n\n{error}")
            return
        self._connect_button.setEnabled(False)
        self._connect_button.setText(f"🔗 {tr('settings.connect_waiting')}")
        worker = ConnectDiscordWorker(config, parent=self)
        worker.browserRequested.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        worker.done.connect(self._on_connect_done)
        worker.finished.connect(lambda: self._reset_connect_button())
        self._connect_worker = worker
        worker.start()

    def _reset_connect_button(self) -> None:
        self._connect_button.setEnabled(True)
        self._connect_button.setText(f"🔗 {tr('settings.connect_discord')}")
        self._connect_worker = None

    def _on_connect_done(self, summary) -> None:
        if summary.status == "ok":
            self._start_create()
            self._url.setText(summary.webhook_url)
            self._name.setText(f"Discord · {summary.channel_id}" if summary.channel_id else "Discord")
            self._name.selectAll()
            self._name.setFocus()
            self._test_result.setText(tr("settings.connect_prefill"))
            self._test_result.setStyleSheet("color:#34D399;")
            return
        key = {"timeout": "settings.connect_timeout",
               "cancelled": "settings.connect_cancelled"}.get(summary.status, "settings.connect_failed")
        QMessageBox.warning(self, tr("settings.connect_discord"),
                            f"{tr(key)}\n\n{summary.error_message}")

    def done(self, result: int) -> None:
        worker = self._connect_worker
        if worker is not None:
            try:
                worker.finished.disconnect(self._reset_connect_button)
                worker.done.disconnect(self._on_connect_done)
            except (TypeError, RuntimeError):
                pass
            worker.abort()
            worker.wait(1500)
            self._connect_worker = None
        super().done(result)

    def _show_form_error(self, text: str) -> None:
        self._form_error.setText(text)
        self._form_error.show()

    # --------------------------------------------------------- sending tab
    def _build_sending_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        box_mode = QGroupBox(tr("send.mode"), page)
        mode_layout = QVBoxLayout(box_mode)
        self._send_mode = QComboBox(box_mode)
        self._send_mode.addItem(tr("settings.send_mode_ask"), "ask")
        self._send_mode.addItem(tr("send.mode_single"), "single")
        self._send_mode.addItem(tr("send.mode_separate"), "separate")
        self._send_mode.currentIndexChanged.connect(self._on_sending_changed)
        mode_layout.addWidget(self._send_mode)
        hint = QLabel(tr("settings.ask_hint"), box_mode)
        hint.setWordWrap(True)
        hint.setObjectName("Dim")
        mode_layout.addWidget(hint)
        layout.addWidget(box_mode)

        box_style = QGroupBox(tr("send.style"), page)
        style_layout = QVBoxLayout(box_style)
        self._style = QComboBox(box_style)
        self._style.addItem(tr("send.style_text"), "text")
        self._style.addItem(tr("send.style_embed"), "embed")
        self._style.currentIndexChanged.connect(self._on_sending_changed)
        style_layout.addWidget(self._style)
        layout.addWidget(box_style)

        self._duplicate = QCheckBox(tr("send.duplicate_caption"), page)
        self._duplicate.toggled.connect(self._on_sending_changed)
        layout.addWidget(self._duplicate)

        self._clear_fields = QCheckBox(tr("settings.clear_fields"), page)
        self._clear_fields.toggled.connect(self._on_sending_changed)
        layout.addWidget(self._clear_fields)

        self._saved_label = QLabel("", page)
        self._saved_label.setObjectName("Dim")
        layout.addWidget(self._saved_label)
        layout.addStretch(1)
        return page

    def _load_sending(self) -> None:
        settings = self._store.settings
        self._set_combo(self._send_mode, settings.send_mode)
        self._set_combo(self._style, settings.section_style)
        self._duplicate.setChecked(settings.duplicate_caption)
        self._clear_fields.setChecked(settings.clear_fields_after_send)

    def _on_sending_changed(self, *_args) -> None:
        settings = self._store.settings
        settings.send_mode = str(self._send_mode.currentData())
        settings.section_style = str(self._style.currentData())
        settings.duplicate_caption = self._duplicate.isChecked()
        settings.clear_fields_after_send = self._clear_fields.isChecked()
        self._store.save()
        self._saved_label.setText(tr("settings.saved"))
        self.sendingDefaultsChanged.emit()

    @staticmethod
    def _set_combo(combo: QComboBox, data: str) -> None:
        index = combo.findData(data)
        combo.setCurrentIndex(index if index >= 0 else 0)

    # ------------------------------------------------------------ app tab
    def _build_app_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        lang_box = QGroupBox(tr("settings.language"), page)
        lang_layout = QVBoxLayout(lang_box)
        self._language = QComboBox(lang_box)
        self._language.addItem("Русский", "ru")
        self._language.addItem("English", "en")
        index = self._language.findData(self._store.settings.language)
        self._language.setCurrentIndex(index if index >= 0 else 0)
        self._language.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self._language)
        self._lang_note = QLabel(tr("settings.language_restart"), lang_box)
        self._lang_note.setObjectName("Dim")
        self._lang_note.setWordWrap(True)
        self._lang_note.hide()
        lang_layout.addWidget(self._lang_note)
        layout.addWidget(lang_box)

        cache_box = QGroupBox(tr("settings.cache"), page)
        cache_layout = QVBoxLayout(cache_box)
        self._keep_cache = QCheckBox(tr("settings.cache_keep"), cache_box)
        self._keep_cache.setChecked(self._store.settings.keep_local_cache)
        self._keep_cache.toggled.connect(self._on_keep_cache_changed)
        cache_layout.addWidget(self._keep_cache)
        self._cache_stats = QLabel("", cache_box)
        self._cache_stats.setObjectName("Dim")
        cache_layout.addWidget(self._cache_stats)
        clear_button = QPushButton(tr("settings.cache_clear"), cache_box)
        clear_button.setObjectName("Danger")
        clear_button.clicked.connect(self._clear_cache)
        cache_layout.addWidget(clear_button)
        layout.addWidget(cache_box)

        backup_box = QGroupBox(tr("settings.backup"), page)
        backup_layout = QVBoxLayout(backup_box)
        warning = QLabel(tr("settings.backup_warning"), backup_box)
        warning.setWordWrap(True)
        warning.setObjectName("Dim")
        backup_layout.addWidget(warning)
        backup_row = QHBoxLayout()
        export_button = QPushButton(tr("settings.export"), backup_box)
        export_button.clicked.connect(self._export_bundle)
        backup_row.addWidget(export_button)
        import_button = QPushButton(tr("settings.import"), backup_box)
        import_button.clicked.connect(self._import_bundle)
        backup_row.addWidget(import_button)
        backup_row.addStretch(1)
        backup_layout.addLayout(backup_row)
        layout.addWidget(backup_box)
        layout.addStretch(1)
        return page

    def _on_language_changed(self, *_args) -> None:
        self._store.settings.language = str(self._language.currentData())
        self._store.save()
        self._lang_note.show()

    def _on_keep_cache_changed(self, checked: bool) -> None:
        self._store.settings.keep_local_cache = checked
        self._store.save()

    def _refresh_cache_stats(self) -> None:
        files, size = cache_store.cache_stats()
        if size < 1024 * 1024:
            human = f"{size / 1024:,.0f} КБ"
        else:
            human = f"{size / 1024 / 1024:,.1f} МБ"
        self._cache_stats.setText(tr("settings.cache_stats", files=files, size=human))

    def _clear_cache(self) -> None:
        answer = QMessageBox.question(self, tr("settings.cache_clear"),
                                      tr("settings.cache_clear_confirm"),
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        removed, freed = cache_store.clear_cache()
        self._refresh_cache_stats()
        QMessageBox.information(self, tr("settings.cache_clear"),
                                tr("settings.cache_cleared", files=removed))

    def _export_bundle(self) -> None:
        target, _filter = QFileDialog.getSaveFileName(
            self, tr("settings.export"), "screensaver-discord-backup.json",
            "JSON (*.json)")
        if not target:
            return
        try:
            transfer.export_bundle(Path(target))
        except OSError as exc:
            QMessageBox.warning(self, tr("settings.export"), str(exc))
            return
        QMessageBox.information(self, tr("settings.export"),
                                tr("settings.export_done", path=target))

    def _import_bundle(self) -> None:
        source, _filter = QFileDialog.getOpenFileName(
            self, tr("settings.import"), "", "JSON (*.json)")
        if not source:
            return
        answer = QMessageBox.question(
            self, tr("settings.import"), tr("settings.import_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            result = transfer.import_bundle(Path(source))
        except transfer.TransferError as exc:
            QMessageBox.warning(self, tr("settings.import"), str(exc))
            return
        QMessageBox.information(
            self, tr("settings.import"),
            tr("settings.import_done", path=str(result.backup_dir)))
        self.configImported.emit()
