"""Application entry point. / Точка входа приложения.

Run with: python main.py   (or via start.bat on Windows)
Запуск: python main.py     (либо через start.bat в Windows)
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app import __version__
from app.i18n import set_language, translator
from app.store import ConfigStore
from app.theme import apply_theme
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("screensaver-into-discord")
    app.setApplicationDisplayName("Screensaver into Discord")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("screensaver-into-discord")

    # apply the saved UI language before any widget is built
    set_language(ConfigStore().settings.language)
    translator()  # warm the language pack (avoids a first-show hitch)
    apply_theme(app)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
