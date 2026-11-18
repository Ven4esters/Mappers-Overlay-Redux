"""Main window (module 1: branded skeleton). / Главное окно (модуль 1: скелет).

Later modules plug in the capture queue, album sidebar, send pipeline and
settings. See README (Project status) for the roadmap.
Дальше сюда встраиваются очередь захвата, сайдбар альбомов, отправка и настройки.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.i18n import tr
from app.theme import COLORS


class MainWindow(QMainWindow):
    """Top-level window: sidebar + central empty state. / Основное окно приложения."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("app.window_title"))
        self.resize(1180, 720)
        self.setMinimumSize(960, 600)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_empty_state(), stretch=1)

        self._status = QStatusBar(self)
        self.setStatusBar(self._status)
        self._status.showMessage(tr("status.skeleton"))

    # ------------------------------------------------------------------ UI
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(self)
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)

        mark = QLabel("S→D", sidebar)
        mark.setStyleSheet(
            f"background:{COLORS['accent']}; color:#FFFFFF; border-radius:10px;"
            "font-weight:800; font-size:18px; padding:10px 14px;"
        )
        mark.setFixedWidth(64)
        layout.addWidget(mark)

        title = QLabel(tr("app.window_title"), sidebar)
        title.setWordWrap(True)
        title.setStyleSheet("font-weight:700; font-size:15px; padding:4px 2px 0 2px;")
        layout.addWidget(title)

        version = QLabel(tr("app.version", version=__version__), sidebar)
        version.setObjectName("Dim")
        layout.addWidget(version)

        layout.addSpacing(18)
        layout.addWidget(self._section_label(tr("nav.albums")))
        layout.addWidget(self._nav_button(f"▤  {tr('nav.albums')}"))
        layout.addWidget(self._nav_button(f"⚡  {tr('nav.profiles')}"))
        layout.addWidget(self._nav_button(f"🕘  {tr('nav.history')}"))

        layout.addStretch(1)
        layout.addWidget(self._nav_button(f"⚙  {tr('nav.settings')}"))
        return sidebar

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        return label

    def _nav_button(self, text: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName("Ghost")
        button.setEnabled(False)
        button.setToolTip(tr("common.coming_soon"))
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _build_empty_state(self) -> QWidget:
        wrapper = QWidget(self)
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(48, 48, 48, 48)

        card = QFrame(wrapper)
        card.setObjectName("Card")
        card.setMaximumWidth(560)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(14)

        icon = QLabel("🖼️", card)
        icon.setStyleSheet("font-size:44px;")
        icon.setAlignment(Qt.AlignHCenter)
        layout.addWidget(icon)

        title = QLabel(tr("empty.title"), card)
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignHCenter)
        layout.addWidget(title)

        subtitle = QLabel(tr("empty.subtitle"), card)
        subtitle.setObjectName("Subtitle")
        subtitle.setAlignment(Qt.AlignHCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        for label in (tr("capture.fullscreen"), tr("capture.active_window"), tr("capture.region")):
            button = QPushButton(label, card)
            button.setEnabled(False)
            button.setToolTip(tr("common.coming_soon"))
            buttons.addWidget(button)
        layout.addLayout(buttons)

        outer.addStretch(1)
        outer.addWidget(card, alignment=Qt.AlignHCenter)
        outer.addStretch(1)
        return wrapper
