"""Подготовка окружения и запуск оверлея.

Скрипт вызывается из ``run_mapper.bat``: проверяет Python 3.12, создаёт ``.venv``,
ставит зависимости и запускает ``main.py``. Любая ошибка объясняется человеку и
попадает в ``logs\\setup.log`` — консоль не закрывается молча.

Коды выхода: 0 — успех, 1 — непредвиденная ошибка, 2 — нет подходящего Python,
3 — не удалось создать venv, 4 — не удалось поставить зависимости,
5 — приложение не запустилось.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MIN_PYTHON = (3, 12)
ABSOLUTE_MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "setup.log"
START_TIMEOUT = 60.0
EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_PYTHON = 2
EXIT_VENV = 3
EXIT_DEPS = 4
EXIT_LAUNCH = 5

LOGGER = logging.getLogger("bootstrap")


def configure_console() -> None:
    """Печатает русский текст даже в консоли с cp866."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def configure_logging(debug: bool) -> None:
    """Пишет журнал установки в logs/setup.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Аргументы лаунчера."""
    parser = argparse.ArgumentParser(description="Подготовка окружения LSP Mapper Overlay")
    parser.add_argument("--debug", action="store_true", help="подробный журнал установки")
    parser.add_argument("--check-only", action="store_true", help="только проверить окружение")
    parser.add_argument(
        "--install-only",
        action="store_true",
        help="поставить окружение и зависимости, но не запускать приложение",
    )
    parser.add_argument("--reinstall", action="store_true", help="пересоздать .venv")
    parser.add_argument(
        "--start-timeout", type=float, default=START_TIMEOUT, help="ожидание старта, с"
    )
    parser.add_argument(
        "--python",
        default=None,
        help="путь к интерпретатору (по умолчанию ищется Python 3.12)",
    )
    return parser.parse_args(argv)


def find_python(explicit: str | None) -> tuple[str, tuple[int, int]] | None:
    """Ищет интерпретатор и возвращает путь вместе с версией.

    Явно указанный ``--python`` принимается начиная с 3.10 (с предупреждением):
    так лаунчер можно проверить на машине без 3.12. Без флага — только 3.12+.
    """
    if explicit:
        version = _probe_version(explicit)
        if version is not None and version >= ABSOLUTE_MIN_PYTHON:
            if version < MIN_PYTHON:
                LOGGER.warning(
                    "Указан Python %s.%s, рекомендуется %s.%s",
                    version[0],
                    version[1],
                    MIN_PYTHON[0],
                    MIN_PYTHON[1],
                )
            return explicit, version
        return None

    candidates = ["py -3.12", "python3.12", "python"]
    for candidate in candidates:
        if not candidate:
            continue
        version = _probe_version(candidate)
        if version is not None and version >= MIN_PYTHON:
            return candidate, version
    return None


def _probe_version(command: str) -> tuple[int, int] | None:
    """Спрашивает у интерпретатора его версию."""
    parts = command.split()
    try:
        output = subprocess.run(  # noqa: S603 - команда задана заранее
            [*parts, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if output.returncode != 0:
        return None
    try:
        major, minor = (int(part) for part in output.stdout.strip().split(".")[:2])
    except ValueError:
        return None
    return (major, minor)


def venv_python() -> Path:
    """Путь к интерпретатору внутри .venv."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def create_venv(python: str, reinstall: bool) -> bool:
    """Создаёт venv (при необходимости пересоздаёт)."""
    if reinstall and VENV_DIR.exists():
        LOGGER.info("Удаляю старый .venv")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    if venv_python().exists():
        LOGGER.info("Виртуальное окружение уже есть: %s", VENV_DIR)
        return True
    LOGGER.info("Создаю виртуальное окружение в %s", VENV_DIR)
    result = subprocess.run(  # noqa: S603
        [*python.split(), "-m", "venv", str(VENV_DIR)], check=False
    )
    if result.returncode != 0:
        LOGGER.error("Не удалось создать .venv (код %s)", result.returncode)
        return False
    return venv_python().exists()


def install_dependencies() -> bool:
    """Ставит runtime-зависимости из requirements.txt."""
    requirements = ROOT / "requirements.txt"
    if not requirements.exists():
        LOGGER.error("Не найден %s", requirements)
        return False
    LOGGER.info("Устанавливаю зависимости…")
    result = subprocess.run(  # noqa: S603
        [
            str(venv_python()),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ],
        check=False,
    )
    if result.returncode != 0:
        LOGGER.error("pip завершился с кодом %s", result.returncode)
        return False
    return True


def runtime_report() -> tuple[list[str], bool]:
    """Строки отчёта и признак того, что PySide6 импортируется."""
    interpreter = venv_python()
    lines = [f"Python: {sys.version.split()[0]}", f"Окружение: {interpreter}"]
    probe = subprocess.run(  # noqa: S603 - фиксированная команда
        [
            str(interpreter),
            "-c",
            "import PySide6; print('PySide6 ' + PySide6.__version__)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if probe.returncode == 0:
        lines.append(probe.stdout.strip())
        return lines, True
    lines.append("PySide6: не установлен (проверьте logs/setup.log)")
    return lines, False


def launch(timeout: float) -> bool:
    """Запускает приложение и ждёт маркер готовности окна."""
    marker = LOG_DIR / "session_ready.txt"
    marker.unlink(missing_ok=True)
    LOGGER.info("Запускаю оверлей…")
    process = subprocess.Popen(  # noqa: S603
        [str(venv_python()), str(ROOT / "main.py")],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            LOGGER.info("Окно открылось (маркер %s)", marker.name)
            return True
        if process.poll() is not None:
            LOGGER.error("Приложение завершилось с кодом %s", process.returncode)
            return False
        time.sleep(0.2)
    LOGGER.warning("Маркер готовности не появился за %.0f с, но процесс жив", timeout)
    return process.poll() is None


def prepare_environment(args: argparse.Namespace) -> int:
    """Создаёт venv и ставит зависимости; возвращает 0 при успехе."""
    found = find_python(args.python)
    if found is None:
        print(f"Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее.")
        print("Скачайте с https://www.python.org/downloads/ и поставьте галочку")
        print("«Add python.exe to PATH» при установке.")
        print(f"Подробности: {LOG_FILE}")
        return EXIT_PYTHON
    python, version = found
    LOGGER.info("Использую Python %s.%s (%s)", version[0], version[1], python)

    if not create_venv(python, args.reinstall):
        print(f"Не удалось создать виртуальное окружение. Подробности: {LOG_FILE}")
        return EXIT_VENV
    if not install_dependencies():
        print(f"Не удалось установить зависимости. Подробности: {LOG_FILE}")
        return EXIT_DEPS
    return EXIT_OK


def report_environment() -> int:
    """Печатает версии Python и PySide6; без PySide6 возвращает код 4."""
    report, pyside_ready = runtime_report()
    for line in report:
        print(line)
    if not pyside_ready:
        print(f"Интерфейс не запустится без PySide6. Подробности: {LOG_FILE}")
        return EXIT_DEPS
    print("Окружение готово. Запуск: run_mapper.bat")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа лаунчера."""
    configure_console()
    args = parse_args(argv)
    configure_logging(args.debug)
    LOGGER.info("Каталог проекта: %s", ROOT)

    code = prepare_environment(args)
    if code != EXIT_OK:
        return code
    if args.check_only or args.install_only:
        return report_environment()
    if not launch(args.start_timeout):
        print(f"Приложение не запустилось. Журнал: {LOG_DIR / 'overlay.log'}")
        return EXIT_LAUNCH
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - лаунчер обязан объяснить любую ошибку
        LOGGER.exception("Непредвиденная ошибка лаунчера")
        print(f"Непредвиденная ошибка. Подробности: {LOG_FILE}")
        raise SystemExit(EXIT_UNEXPECTED) from None
