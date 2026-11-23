"""Подготовка окружения и запуск Map Overlay Redux.

Скрипт создаёт ``.venv``, ставит зависимости из ``requirements.txt`` (только если они
изменились) и запускает ``main.py``. Журнал установки — ``logs/setup.log``.

``subprocess`` вызывается только со своими командами (``sys.executable``, ``pip`` из
``.venv``, ``main.py``); внешнего ввода в аргументах нет, шелл не используется.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MARKER = VENV / ".requirements.sha256"
LOG_DIR = ROOT / "logs"
SETUP_LOG = LOG_DIR / "setup.log"

MIN_PYTHON = (3, 10)
PREFERRED_PYTHON = (3, 12)


def _log(message: str, *, is_error: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = "ERROR" if is_error else "INFO"
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {level:5} | {message}"
    with SETUP_LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    print(message)


def venv_python() -> Path:
    """Интерпретатор внутри ``.venv``."""
    relative = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return VENV / relative


def requirements_hash() -> str:
    """Отпечаток файла зависимостей: по нему видно, нужна ли переустановка."""
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def check_python() -> bool:
    """Проверить версию интерпретатора."""
    version = sys.version_info[:2]
    if version < MIN_PYTHON:
        _log(
            "Нужен Python 3.12 (минимум 3.10), запущен "
            f"{version[0]}.{version[1]}. Установите Python с python.org.",
            is_error=True,
        )
        return False
    if version < PREFERRED_PYTHON:
        _log(f"Внимание: запущен Python {version[0]}.{version[1]}, проект рассчитан на 3.12")
    return True


def ensure_venv() -> bool:
    """Создать ``.venv``, если его ещё нет."""
    python = venv_python()
    if python.exists():
        return True
    _log(f"Создаю окружение: {VENV}")
    # Список аргументов без шелла: подставить чужую команду неоткуда.
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "venv", str(VENV)], check=False
    )
    if result.returncode != 0 or not python.exists():
        _log("Не удалось создать виртуальное окружение", is_error=True)
        return False
    return True


def install_requirements() -> bool:
    """Поставить зависимости, если они изменились с прошлого запуска."""
    digest = requirements_hash()
    if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == digest:
        _log("Зависимости уже установлены")
        return True
    _log("Устанавливаю зависимости (первый запуск занимает 1-3 минуты)…")
    python = str(venv_python())
    for command in (
        [python, "-m", "pip", "install", "--upgrade", "pip"],
        [python, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
    ):
        result = subprocess.run(command, check=False)  # nosec B603
        if result.returncode != 0:
            _log(f"Команда завершилась с ошибкой: {' '.join(command)}", is_error=True)
            return False
    MARKER.write_text(digest, encoding="utf-8")
    return True


def run_app(extra_args: list[str]) -> int:
    """Запустить приложение и вернуть его код выхода."""
    command = [str(venv_python()), str(ROOT / "main.py"), *extra_args]
    _log("Запускаю оверлей")
    return subprocess.run(command, check=False).returncode  # nosec B603


def main(argv: list[str] | None = None) -> int:
    """Точка входа скрипта подготовки."""
    parser = argparse.ArgumentParser(description="Подготовка окружения Map Overlay Redux")
    parser.add_argument("--setup-only", action="store_true", help="только подготовить окружение")
    known, extra = parser.parse_known_args(argv)
    if not check_python() or not ensure_venv() or not install_requirements():
        return 1
    if known.setup_only:
        _log("Окружение готово")
        return 0
    return run_app(extra)


if __name__ == "__main__":
    raise SystemExit(main())
