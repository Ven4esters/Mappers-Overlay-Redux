"""Запуск оверлея из исходников: ``python main.py``."""

from __future__ import annotations

import sys

from lsp_overlay.app import main

if __name__ == "__main__":
    sys.exit(main())
