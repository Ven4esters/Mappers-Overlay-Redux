"""Application entry point. / Точка входа приложения.

Logging is configured before *any* project import so even import-time crashes
(like a missing Qt symbol) land in screensaver.log with a traceback.
Логирование настраивается до любых проектных импортов — падение при импорте
(например, отсутствующий символ Qt) тоже попадёт в screensaver.log с трейсбеком.

Run with: python main.py   (or via start.bat on Windows)
Запуск: python main.py     (либо через start.bat в Windows)
"""

from __future__ import annotations

import logging
import sys

from app.logging_setup import log_path, setup_logging

_log_path = setup_logging()
log = logging.getLogger("screensaver.main")
log.info("starting Screensaver into Discord (log: %s)", _log_path)


def _excepthook(exc_type, exc_value, traceback_obj) -> None:
    log.critical("unhandled exception", exc_info=(exc_type, exc_value, traceback_obj))
    sys.__excepthook__(exc_type, exc_value, traceback_obj)


sys.excepthook = _excepthook

try:
    from PySide6.QtWidgets import QApplication

    from app import __version__
    from app.i18n import set_language, translator
    from app.store import ConfigStore
    from app.theme import apply_theme
    from app.ui.main_window import MainWindow
except Exception:  # noqa: BLE001 — the whole point: log, don't vanish
    log.critical("startup failed while importing application modules — "
                 "run 'python -m pip install -r requirements.txt' again",
                 exc_info=True)
    raise


def main() -> int:
    log.info("version %s | python %s on %s", __version__, sys.version.split()[0], sys.platform)
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("screensaver-into-discord")
        app.setApplicationDisplayName("Screensaver into Discord")
        app.setApplicationVersion(__version__)
        app.setOrganizationName("screensaver-into-discord")

        # apply the saved UI language before any widget is built
        set_language(ConfigStore().settings.language)
        translator()  # warm the language pack (avoids a first-show hitch)
        apply_theme(app)

        log.info("creating main window")
        window = MainWindow()
        window.show()
        log.info("main window shown; entering event loop")
        return app.exec()
    except Exception:  # noqa: BLE001
        log.critical("fatal error during startup", exc_info=True)
        raise


if __name__ == "__main__":
    sys.exit(main())
