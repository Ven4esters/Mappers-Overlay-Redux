"""Send panel: caption fields, mode toggles, send button, progress. / Панель отправки."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QTextEdit, QVBoxLayout,
)

from app.i18n import tr


class SendPanel(QFrame):
    sendRequested = Signal()
    cancelRequested = Signal()
    resetCounterRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        layout.addWidget(self._section_label(tr("send.target")))
        self._album_label = QLabel(tr("album.none_selected"), self)
        self._album_label.setWordWrap(True)
        self._album_label.setStyleSheet("font-weight:700; font-size:15px;")
        layout.addWidget(self._album_label)

        layout.addWidget(self._section_label(tr("section.name_label")))
        self._name = QLineEdit(self)
        self._name.setPlaceholderText(tr("section.name_placeholder"))
        self._name.textChanged.connect(self._refresh_name_counter)
        layout.addWidget(self._name)

        desc_head = QHBoxLayout()
        desc_head.addWidget(self._section_label(tr("section.desc_label")))
        desc_head.addStretch(1)
        self._counter = QLabel("0", self)
        self._counter.setObjectName("Dim")
        desc_head.addWidget(self._counter)
        layout.addLayout(desc_head)
        self._description = QTextEdit(self)
        self._description.setPlaceholderText(tr("section.desc_placeholder"))
        self._description.setFixedHeight(96)
        self._description.textChanged.connect(self._refresh_desc_counter)
        layout.addWidget(self._description)

        layout.addWidget(self._section_label(tr("send.mode")))
        self._mode = QComboBox(self)
        self._mode.addItem(tr("send.mode_single"), "single")
        self._mode.addItem(tr("send.mode_separate"), "separate")
        layout.addWidget(self._mode)

        self._duplicate = QCheckBox(tr("send.duplicate_caption"), self)
        layout.addWidget(self._duplicate)

        layout.addWidget(self._section_label(tr("send.style")))
        self._style = QComboBox(self)
        self._style.addItem(tr("send.style_text"), "text")
        self._style.addItem(tr("send.style_embed"), "embed")
        layout.addWidget(self._style)

        number_row = QHBoxLayout()
        self._number_label = QLabel(tr("send.next_number", n=1), self)
        self._number_label.setObjectName("Dim")
        number_row.addWidget(self._number_label, stretch=1)
        self._reset_number = QPushButton(tr("send.reset_number"), self)
        self._reset_number.setObjectName("Ghost")
        self._reset_number.clicked.connect(self.resetCounterRequested.emit)
        number_row.addWidget(self._reset_number)
        layout.addLayout(number_row)

        layout.addStretch(1)

        self._send = QPushButton(tr("send.button_short"), self)
        self._send.setObjectName("Primary")
        self._send.setMinimumHeight(42)
        self._send.setStyleSheet("font-size:14px;")
        self._send.clicked.connect(self.sendRequested.emit)
        layout.addWidget(self._send)

        self._cancel = QPushButton(tr("send.cancel"), self)
        self._cancel.setObjectName("Danger")
        self._cancel.clicked.connect(self.cancelRequested.emit)
        self._cancel.hide()
        layout.addWidget(self._cancel)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._result = QLabel(self)
        self._result.setWordWrap(True)
        self._result.setOpenExternalLinks(True)
        self._result.hide()
        layout.addWidget(self._result)

        self._sending = False
        self._can_send = False
        self._refresh_desc_counter()
        self._sync_send_button()

    # -------------------------------------------------------------- state
    def set_album(self, name: str | None, next_number: int = 1, shots: int = 0) -> None:
        self._album_label.setText(name if name else tr("album.none_selected"))
        self._number_label.setText(tr("send.next_number", n=next_number))
        self._send.setText(tr("send.button", album=name) if name else tr("send.button_short"))
        self._album_label.setToolTip(tr("send.album_shots", n=shots))
        self._sync_send_button()

    def set_can_send(self, can_send: bool) -> None:
        self._can_send = can_send
        self._sync_send_button()

    def set_sending(self, sending: bool, total: int = 0) -> None:
        self._sending = sending
        self._send.hide() if sending else self._send.show()
        self._cancel.show() if sending else self._cancel.hide()
        self._progress.show() if sending else self._progress.hide()
        if sending:
            self._progress.setRange(0, max(1, total))
            self._progress.setValue(0)
        for widget in (self._name, self._description, self._mode, self._duplicate,
                       self._style, self._reset_number):
            widget.setEnabled(not sending)
        self._sync_send_button()

    def set_progress(self, done: int, total: int) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        self._progress.setFormat(tr("send.progress", done=done, total=total))

    def show_ok(self, message_url: str) -> None:
        self._result.setText(
            f'{tr("result.ok")}' + (f' · <a href="{message_url}">{tr("result.open_link")}</a>' if message_url else ""))
        self._result.setStyleSheet(f"color:{'#34D399'};")
        self._result.show()

    def show_error(self, text: str) -> None:
        self._result.setText(f'⚠ {text}')
        self._result.setStyleSheet("color:#F87171;")
        self._result.show()

    def clear_caption_fields(self) -> None:
        self._name.clear()
        self._description.clear()
        self._refresh_name_counter()
        self._refresh_desc_counter()

    def clear_result(self) -> None:
        self._result.hide()

    def highlight_name_error(self) -> None:
        self._name.setStyleSheet("border: 2px solid #F87171;")
        self._name.setFocus()

    def clear_name_error(self) -> None:
        self._name.setStyleSheet("")

    # ------------------------------------------------------------- inputs
    def section_name(self) -> str:
        return self._name.text().strip()

    def description(self) -> str:
        return self._description.toPlainText().strip()

    def send_mode(self) -> str:
        return str(self._mode.currentData())

    def set_send_mode(self, mode: str) -> None:
        index = self._mode.findData(mode)
        if index >= 0:
            self._mode.setCurrentIndex(index)

    def style(self) -> str:
        return str(self._style.currentData())

    def set_style(self, style: str) -> None:
        index = self._style.findData(style)
        if index >= 0:
            self._style.setCurrentIndex(index)

    def set_duplicate_caption(self, enabled: bool) -> None:
        self._duplicate.setChecked(enabled)

    def duplicate_caption(self) -> bool:
        return self._duplicate.isChecked()

    # ------------------------------------------------------------- helpers
    def _sync_send_button(self) -> None:
        self._send.setEnabled(self._can_send and not self._sending)

    def _refresh_name_counter(self) -> None:
        self.clear_name_error()

    def _refresh_desc_counter(self) -> None:
        if hasattr(self, "_description"):
            text = self._description.toPlainText()
            self._counter.setText(f"{len(text)}/4096")

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        return label
