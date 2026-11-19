"""Settings dialog: webhook profiles, sending defaults, app (cache/language/backup/about).
Диалог настроек: профили вебхуков, параметры отправки, приложение (кэш/язык/бэкап/о себе).

Webhooks are the only auth path — there is no OAuth/Discord-login flow; the
page includes step-by-step instructions on how to create a webhook URL.
Вход только через вебхук — никакого OAuth; на странице есть инструкция,
как создать URL вебхука.

Capture hotkey is configurable (default PrtSc, usually owned by Windows
Snipping Tool) — «Горячие клавиши» on the app page.
Горячую клавишу снимка можно менять (по умолчанию PrtSc — его обычно забирает
«Ножницы» Windows) — блок «Горячие клавиши» на странице приложения.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app import __version__
from app import cache as cache_store
from app import transfer
from app.discord_client import DiscordClient, DiscordError
from app.i18n import tr
from app.store import ConfigStore
from app.webhook_url import is_webhook_url, parse_webhook_url
from app.hotkey_parse import DEFAULT_HOTKEY, normalize_hotkey
from app.paths import DATA_DIR
from app.ui.widgets import HotkeyRecorder, SegmentedControl

logger = logging.getLogger("screensaver.settings")


def _mask_webhook(url: str) -> str:
    parsed = parse_webhook_url(url)
    return f"…/{parsed[0]}/••••••••" if parsed else "…"


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
    """Modal settings with a left navigation rail. / Модальные настройки с навигацией.

    Signals: profilesChanged — profile set/active changed (main window refreshes);
    sendingDefaultsChanged — sending defaults changed;
    configImported — everything was replaced from a backup bundle.
    """

    profilesChanged = Signal()
    sendingDefaultsChanged = Signal()
    configImported = Signal()
    captureHotkeyChanged = Signal(str)

    def __init__(self, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumSize(880, 620)
        self._store = store
        self._create_mode = False
        self._loading = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_nav())

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 16, 18, 14)
        right_layout.setSpacing(12)
        self._stack = QStackedWidget(right)
        self._stack.addWidget(self._build_profiles_page())
        self._stack.addWidget(self._build_sending_page())
        self._stack.addWidget(self._build_app_page())
        right_layout.addWidget(self._stack, stretch=1)

        footer = QHBoxLayout()
        self._saved_label = QLabel("", right)
        self._saved_label.setObjectName("Dim")
        footer.addWidget(self._saved_label)
        footer.addStretch(1)
        close_buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=right)
        close_buttons.rejected.connect(self.accept)
        footer.addWidget(close_buttons)
        right_layout.addLayout(footer)

        root.addWidget(right, stretch=1)

        self._nav_buttons[0].setChecked(True)
        self._stack.setCurrentIndex(0)
        self._load_profiles()
        self._load_sending()
        self._refresh_cache_stats()

    # ---------------------------------------------------------------- nav
    def _build_nav(self) -> QWidget:
        rail = QWidget(self)
        rail.setObjectName("Sidebar")
        rail.setFixedWidth(196)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(4)

        title = QLabel(tr("settings.title"), rail)
        title.setObjectName("SectionHeader")
        layout.addWidget(title)
        subtitle = QLabel(tr("settings.subtitle"), rail)
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(10)

        icons = ["👤", "✈", "⚙"]
        labels = [tr("settings.tab_profiles"), tr("settings.tab_sending"), tr("settings.tab_app")]
        self._nav_buttons: list[QPushButton] = []
        for index, (icon, label) in enumerate(zip(icons, labels)):
            button = QPushButton(f"{icon}   {label}", rail)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, row=index: self._nav_to(row))
            self._nav_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        return rail

    def _nav_to(self, row: int) -> None:
        for index, button in enumerate(self._nav_buttons):
            button.setChecked(index == row)
        self._stack.setCurrentIndex(row)

    # --------------------------------------------------------- profiles page
    def _build_profiles_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        box = QGroupBox(tr("settings.profiles_group"), page)
        row = QHBoxLayout(box)
        row.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        self._profile_list = QListWidget(box)
        self._profile_list.setMinimumWidth(188)
        self._profile_list.itemSelectionChanged.connect(self._on_profile_selected)
        left.addWidget(self._profile_list, stretch=1)
        self._new_button = QPushButton(f"＋  {tr('settings.profile_new')}", box)
        self._new_button.clicked.connect(self._start_create)
        left.addWidget(self._new_button)
        small_row = QHBoxLayout()
        small_row.setSpacing(6)
        self._activate_button = QPushButton(f"★ {tr('settings.profile_activate')}", box)
        self._activate_button.setObjectName("Ghost")
        self._activate_button.clicked.connect(self._activate_profile)
        small_row.addWidget(self._activate_button, stretch=1)
        self._remove_button = QPushButton(tr("settings.profile_remove"), box)
        self._remove_button.setObjectName("Danger")
        self._remove_button.clicked.connect(self._remove_profile)
        small_row.addWidget(self._remove_button, stretch=1)
        left.addLayout(small_row)
        row.addLayout(left, stretch=2)

        form_host = QWidget(box)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
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

        self._type = SegmentedControl(
            [("forum", f"🏟  {tr('settings.type_forum')}"), ("text", f"💬  {tr('settings.type_text')}")],
            form_host)
        form.addRow(tr("settings.profile_type"), self._type)

        self._username = QLineEdit(form_host)
        self._username.setPlaceholderText(tr("settings.profile_username_ph"))
        form.addRow(tr("settings.profile_username"), self._username)

        self._avatar = QLineEdit(form_host)
        self._avatar.setPlaceholderText("https://…/avatar.png")
        form.addRow(tr("settings.profile_avatar"), self._avatar)

        test_row = QHBoxLayout()
        self._test_button = QPushButton(f"⚡  {tr('settings.test')}", form_host)
        self._test_button.clicked.connect(self._test_webhook)
        test_row.addWidget(self._test_button)
        self._test_result = QLabel("", form_host)
        self._test_result.setWordWrap(True)
        self._test_result.setObjectName("Dim")
        test_row.addWidget(self._test_result, stretch=1)
        form.addRow("", test_row)

        self._form_error = QLabel("", form_host)
        self._form_error.setWordWrap(True)
        self._form_error.setStyleSheet("color:#F87171;")
        self._form_error.hide()
        form.addRow("", self._form_error)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self._save_button = QPushButton(tr("common.save"), form_host)
        self._save_button.setObjectName("Primary")
        self._save_button.setMinimumWidth(140)
        self._save_button.clicked.connect(self._save_profile)
        save_row.addWidget(self._save_button)
        form.addRow("", save_row)

        row.addWidget(form_host, stretch=3)
        layout.addWidget(box, stretch=1)

        help_box = QGroupBox(tr("settings.help_group"), page)
        help_layout = QVBoxLayout(help_box)
        help_layout.setSpacing(6)
        for key in ("settings.help_step1", "settings.help_step2", "settings.help_step3"):
            step = QLabel(tr(key), help_box)
            step.setWordWrap(True)
            help_layout.addWidget(step)
        note = QLabel(tr("settings.help_note"), help_box)
        note.setObjectName("Hint")
        note.setWordWrap(True)
        help_layout.addWidget(note)
        help_row = QHBoxLayout()
        help_link = QPushButton(tr("settings.help_link"), help_box)
        help_link.setObjectName("Ghost")
        help_link.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://discord.com/developers/docs/resources/webhook")))
        help_row.addWidget(help_link, 0, Qt.AlignLeft)
        help_row.addStretch(1)
        help_layout.addLayout(help_row)
        layout.addWidget(help_box)
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
            item.setToolTip(_mask_webhook(profile.webhook_url))
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
        if not self._profile_list.count():
            # nothing to select (no profiles yet) — start in "new profile" mode
            self._start_create()

    def selected_profile_id(self) -> str:
        item = self._profile_list.currentItem()
        return str(item.data(Qt.UserRole)) if item else ""

    def _on_profile_selected(self) -> None:
        if self._loading:
            return
        # clicking a profile always edits it (exits any half-finished "new profile" draft)
        profile = self._store.get_profile(self.selected_profile_id())
        if profile is None:
            # no selection = new-profile mode (Save must not fail with "not found")
            self._clear_form()
            self._set_buttons_for_mode(create=True)
            return
        self._fill_form(profile)
        self._set_buttons_for_mode(create=False)

    def _fill_form(self, profile) -> None:
        self._name.setText(profile.name)
        self._url.setText(profile.webhook_url)
        self._type.set_current(profile.channel_type if profile.channel_type in ("forum", "text") else "forum")
        self._username.setText(profile.username_override)
        self._avatar.setText(profile.avatar_url)
        self._test_result.clear()
        self._form_error.hide()

    def _clear_form(self) -> None:
        self._name.clear()
        self._url.clear()
        self._type.set_current("forum")
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
        channel_type = self._type.current()
        username = self._username.text().strip()
        avatar = self._avatar.text().strip()
        # empty selection ⇒ treat as a new profile (add_profile), never as a broken update
        create = self._create_mode or not self.selected_profile_id()
        try:
            if create:
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
        logger.info("profile saved (%s: %r)", "new" if create else "edit", profile.name)
        self._set_buttons_for_mode(create=False)
        self._load_profiles(select_id=profile.id)
        self._flash_saved()
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
        logger.info("profile removed: %r", profile.name)
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
        self._flash_saved()
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
            logger.warning("webhook check failed: %s", exc.code)
            self._test_result.setText(f"✗ {_friendly_error(exc.code)}")
            self._test_result.setStyleSheet("color:#F87171;")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._test_button.setEnabled(True)
        name = str(info.get("name", "?"))
        channel = str(info.get("channel_id", "?"))
        logger.info("webhook check ok (channel_id=%s)", channel)
        guild = str(info.get("guild_id", ""))
        detail = f"{name} · #{channel}" + (f" · guild {guild}" if guild else "")
        self._test_result.setText(f"✓ {tr('settings.test_ok')}: {detail}")
        self._test_result.setStyleSheet("color:#34D399;")

    def _show_form_error(self, text: str) -> None:
        self._form_error.setText(text)
        self._form_error.show()

    # --------------------------------------------------------- sending page
    def _build_sending_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        mode_box = QGroupBox(tr("send.mode"), page)
        mode_layout = QVBoxLayout(mode_box)
        self._mode_ask = QRadioButton(tr("settings.send_mode_ask"), mode_box)
        self._mode_ask.setToolTip(tr("settings.ask_hint"))
        self._mode_single = QRadioButton(tr("send.mode_single"), mode_box)
        self._mode_separate = QRadioButton(tr("send.mode_separate"), mode_box)
        for radio in (self._mode_ask, self._mode_single, self._mode_separate):
            radio.toggled.connect(self._on_sending_changed)
            mode_layout.addWidget(radio)
        hint = QLabel(tr("settings.ask_hint"), mode_box)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        mode_layout.addWidget(hint)
        layout.addWidget(mode_box)

        style_box = QGroupBox(tr("send.style"), page)
        style_layout = QVBoxLayout(style_box)
        self._style_text = QRadioButton(tr("send.style_text"), style_box)
        self._style_embed = QRadioButton(tr("send.style_embed"), style_box)
        for radio in (self._style_text, self._style_embed):
            radio.toggled.connect(self._on_sending_changed)
            style_layout.addWidget(radio)
        layout.addWidget(style_box)

        options_box = QGroupBox(tr("settings.options_group"), page)
        options_layout = QVBoxLayout(options_box)
        self._duplicate = QCheckBox(tr("send.duplicate_caption"), options_box)
        self._duplicate.toggled.connect(self._on_sending_changed)
        options_layout.addWidget(self._duplicate)
        self._clear_fields = QCheckBox(tr("settings.clear_fields"), options_box)
        self._clear_fields.toggled.connect(self._on_sending_changed)
        options_layout.addWidget(self._clear_fields)
        layout.addWidget(options_box)
        layout.addStretch(1)
        return page

    def _load_sending(self) -> None:
        # block toggled-handlers so opening the dialog doesn't re-save/re-emit
        radios = [self._mode_ask, self._mode_single, self._mode_separate,
                  self._style_text, self._style_embed, self._duplicate, self._clear_fields]
        for widget in radios:
            widget.blockSignals(True)
        settings = self._store.settings
        self._mode_ask.setChecked(settings.send_mode == "ask")
        self._mode_single.setChecked(settings.send_mode == "single")
        self._mode_separate.setChecked(settings.send_mode == "separate")
        self._style_text.setChecked(settings.section_style != "embed")
        self._style_embed.setChecked(settings.section_style == "embed")
        self._duplicate.setChecked(settings.duplicate_caption)
        self._clear_fields.setChecked(settings.clear_fields_after_send)
        for widget in radios:
            widget.blockSignals(False)

    def _on_sending_changed(self, *_args) -> None:
        settings = self._store.settings
        settings.send_mode = "ask" if self._mode_ask.isChecked() else "separate" if self._mode_separate.isChecked() else "single"
        settings.section_style = "embed" if self._style_embed.isChecked() else "text"
        settings.duplicate_caption = self._duplicate.isChecked()
        settings.clear_fields_after_send = self._clear_fields.isChecked()
        self._store.save()
        self._flash_saved()
        self.sendingDefaultsChanged.emit()

    # ------------------------------------------------------------ app page
    def _build_app_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        lang_box = QGroupBox(tr("settings.language"), page)
        lang_layout = QVBoxLayout(lang_box)
        self._language = SegmentedControl([("ru", "Русский"), ("en", "English")], lang_box)
        self._language.set_current(self._store.settings.language)
        self._language.currentChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self._language)
        self._lang_note = QLabel(tr("settings.language_restart"), lang_box)
        self._lang_note.setObjectName("Hint")
        self._lang_note.setWordWrap(True)
        self._lang_note.hide()
        lang_layout.addWidget(self._lang_note)
        layout.addWidget(lang_box)

        hotkeys_box = QGroupBox(tr("settings.hotkeys_group"), page)
        hotkeys_layout = QVBoxLayout(hotkeys_box)
        hotkeys_layout.setSpacing(8)
        hint = QLabel(tr("settings.hotkey_hint"), hotkeys_box)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        hotkeys_layout.addWidget(hint)
        capture_row = QHBoxLayout()
        capture_row.setSpacing(10)
        capture_label = QLabel(tr("settings.hotkey_capture_label"), hotkeys_box)
        capture_row.addWidget(capture_label)
        capture_row.addStretch(1)
        self._hotkey_recorder = HotkeyRecorder(self._store.settings.capture_hotkey, hotkeys_box)
        self._hotkey_recorder.captureFinished.connect(self._on_capture_hotkey)
        self._hotkey_recorder.rejected.connect(self._on_capture_hotkey_rejected)
        capture_row.addWidget(self._hotkey_recorder)
        reset_button = QPushButton(tr("settings.hotkey_reset"), hotkeys_box)
        reset_button.setObjectName("Ghost")
        reset_button.clicked.connect(self._reset_capture_hotkey)
        capture_row.addWidget(reset_button)
        hotkeys_layout.addLayout(capture_row)
        self._hotkey_note = QLabel("", hotkeys_box)
        self._hotkey_note.setObjectName("Hint")
        self._hotkey_note.setWordWrap(True)
        hotkeys_layout.addWidget(self._hotkey_note)
        layout.addWidget(hotkeys_box)

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
        cache_layout.addWidget(clear_button, alignment=Qt.AlignLeft)
        layout.addWidget(cache_box)

        backup_box = QGroupBox(tr("settings.backup"), page)
        backup_layout = QVBoxLayout(backup_box)
        warning = QLabel(tr("settings.backup_warning"), backup_box)
        warning.setObjectName("Hint")
        warning.setWordWrap(True)
        backup_layout.addWidget(warning)
        backup_row = QHBoxLayout()
        export_button = QPushButton(tr("settings.export"), backup_box)
        export_button.clicked.connect(self._export_bundle)
        backup_row.addWidget(export_button)
        import_button = QPushButton(tr("settings.import"), backup_box)
        import_button.setObjectName("Danger")
        import_button.clicked.connect(self._import_bundle)
        backup_row.addWidget(import_button)
        backup_row.addStretch(1)
        backup_layout.addLayout(backup_row)
        layout.addWidget(backup_box)

        about_box = QGroupBox(tr("settings.about_group"), page)
        about_layout = QVBoxLayout(about_box)
        about = QLabel(tr("settings.about_text", version=__version__), about_box)
        about.setWordWrap(True)
        about_layout.addWidget(about)
        log_hint = QLabel(tr("settings.about_log_path", path=str(DATA_DIR / "screensaver.log")), about_box)
        log_hint.setObjectName("Hint")
        log_hint.setWordWrap(True)
        about_layout.addWidget(log_hint)
        link_button = QPushButton(tr("settings.repo_open"), about_box)
        link_button.setObjectName("Primary")
        link_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/Ven4esters/screensaver-into-discord")))
        about_layout.addWidget(link_button, alignment=Qt.AlignLeft)
        layout.addWidget(about_box)
        layout.addStretch(1)
        return page

    def _on_language_changed(self, lang: str) -> None:
        self._store.settings.language = lang
        self._store.save()
        self._lang_note.show()

    def _on_keep_cache_changed(self, checked: bool) -> None:
        self._store.settings.keep_local_cache = checked
        self._store.save()

    def _on_capture_hotkey(self, combo: str) -> None:
        combo = normalize_hotkey(combo) or DEFAULT_HOTKEY
        logger.info("capture hotkey set to %s", combo)
        self._store.settings.capture_hotkey = combo
        self._store.save()
        self._hotkey_note.setStyleSheet("")
        self._hotkey_note.setText(tr("settings.hotkey_applied", combo=combo))
        self._flash_saved()
        self.captureHotkeyChanged.emit(combo)

    def _on_capture_hotkey_rejected(self) -> None:
        self._hotkey_note.setStyleSheet("color: rgba(248, 113, 113, 0.95);")
        self._hotkey_note.setText(tr("settings.hotkey_rejected"))

    def _reset_capture_hotkey(self) -> None:
        self._hotkey_recorder.set_hotkey(DEFAULT_HOTKEY)
        self._on_capture_hotkey(DEFAULT_HOTKEY)

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
        removed, _freed = cache_store.clear_cache()
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

    def _flash_saved(self) -> None:
        self._saved_label.setText(tr("settings.saved"))
