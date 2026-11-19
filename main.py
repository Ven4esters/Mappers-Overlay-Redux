"""Запуск приложения без установки пакета: python main.py [--debug]."""

from __future__ import annotations

from mapper_assist.app import main

if __name__ == "__main__":
    raise SystemExit(main())
