#!/usr/bin/env python3
"""
Подготовка окружения и запуск LSP Mapper Assist.

Запускается из run_mapper.bat системным Python. Делает всю «тяжёлую» работу,
которую ненадёжно писать на batch: создание .venv, установку зависимостей,
запуск приложения с контролем успешного старта и подробным логом.

Ключи:
    --debug         запустить приложение в этом же окне консоли с подробным логом
    --reinstall     принудительно переустановить зависимости
    --repair-venv   удалить .venv и создать окружение заново
    --check-only    только проверить/подготовить окружение, не запуская приложение
    --no-color      не использовать ANSI-цвета (по умолчанию и так выключены)

Коды возврата:
    0 — приложение запущено (или проверка окружения прошла успешно)
    1 — не найден/слишком старый Python
    2 — не удалось создать виртуальное окружение
    3 — не удалось установить зависимости
    4 — приложение не смогло стартовать (см. логи)
    5 — непредвиденная ошибка

Все действия пишутся в logs/setup.log, лог самого приложения — logs/mapper_assist.log.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
LOGS_DIR = ROOT / "logs"
SETUP_LOG = LOGS_DIR / "setup.log"
APP_LOG = LOGS_DIR / "mapper_assist.log"
READY_MARKER = LOGS_DIR / "session_ready.txt"
STAMP_FILE = VENV_DIR / ".deps-stamp"
REQUIREMENTS = ROOT / "requirements.txt"
MAIN_SCRIPT = ROOT / "main.py"
MIN_PYTHON = (3, 10)

EXIT_OK = 0
EXIT_PYTHON = 1
EXIT_VENV = 2
EXIT_DEPS = 3
EXIT_APP = 4
EXIT_UNEXPECTED = 5

IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------------- вывод
def _init_console() -> None:
    """Включает UTF-8 в консоли Windows, чтобы русский текст не превращался в кракозябры."""
    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def log(message: str = "") -> None:
    """Пишет строку в консоль и в logs/setup.log (с меткой времени)."""
    try:
        print(message, flush=True)
    except Exception:  # noqa: BLE001
        print(message.encode("ascii", "replace").decode("ascii"), flush=True)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with SETUP_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except Exception:  # noqa: BLE001
        pass


def section(title: str) -> None:
    log("")
    log("=" * 62)
    log(f" {title}")
    log("=" * 62)


def tail_of(path: Path, lines: int = 25) -> str:
    """Возвращает последние строки файла (пустая строка, если файла нет)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""
    return "\n".join(text.splitlines()[-lines:])


def show_logs_tail(title: str, path: Path, lines: int = 25) -> None:
    tail = tail_of(path, lines)
    if not tail:
        log(f"  ({title}: файл {path} пуст или отсутствует)")
        return
    log(f"  --- последние строки {title} ({path.name}) ---")
    for line in tail.splitlines():
        log(f"  | {line}")
    log("  " + "-" * 40)


# --------------------------------------------------------------------------- утилиты
def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def venv_pythonw() -> Path:
    candidate = VENV_DIR / ("Scripts/pythonw.exe" if IS_WINDOWS else "bin/python")
    return candidate if candidate.exists() else venv_python()


def requirements_hash() -> str:
    try:
        return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()[:32]
    except Exception:  # noqa: BLE001
        return "unknown"


def read_stamp() -> str:
    try:
        return STAMP_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""


def write_stamp(value: str) -> None:
    try:
        STAMP_FILE.write_text(value, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def run_logged(cmd: list[str], timeout: float = 1800.0) -> tuple[int, str]:
    """Запускает команду, дублируя её вывод в logs/setup.log. Возвращает (код, вывод)."""
    log("  $ " + " ".join(cmd))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        log("  ! Команда не завершилась за отведённое время")
        return 1, "timeout"
    except FileNotFoundError as exc:
        log(f"  ! Команда не найдена: {exc}")
        return 1, str(exc)

    output = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with SETUP_LOG.open("a", encoding="utf-8") as fh:
            fh.write(output)
            if output and not output.endswith("\n"):
                fh.write("\n")
    except Exception:  # noqa: BLE001
        pass
    return proc.returncode, output


def python_works(python: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(python), "-c", "import sys"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def imports_ok(python: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(python), "-c", "import PySide6, pyperclip"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=180,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def import_error_text(python: Path) -> str:
    try:
        proc = subprocess.run(
            [str(python), "-c", "import PySide6, pyperclip"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
        return (proc.stdout or b"").decode("utf-8", "replace").strip()
    except Exception as exc:  # noqa: BLE001
        return str(exc)


# --------------------------------------------------------------------------- шаги
def check_python() -> int:
    section("[1/5] Проверка Python")
    version = ".".join(str(p) for p in sys.version_info[:3])
    log(f"  Системный Python: {version} ({sys.executable})")
    if sys.version_info < MIN_PYTHON:
        log("")
        log(f"  [ОШИБКА] Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее, найден {version}.")
        log("  Скачайте актуальный Python: https://www.python.org/downloads/")
        log("  При установке включите галочку «Add python.exe to PATH».")
        return EXIT_PYTHON
    if not MAIN_SCRIPT.exists():
        log(f"  [ОШИБКА] Не найден {MAIN_SCRIPT} — распакуйте архив целиком.")
        return EXIT_UNEXPECTED
    if not REQUIREMENTS.exists():
        log(f"  [ОШИБКА] Не найден {REQUIREMENTS} — распакуйте архив целиком.")
        return EXIT_UNEXPECTED
    return EXIT_OK


def ensure_venv(options: argparse.Namespace) -> int:
    section("[2/5] Виртуальное окружение .venv")
    if options.repair_venv and VENV_DIR.exists():
        log("  Удаляю старое окружение (--repair-venv)...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    if venv_python().exists() and python_works(venv_python()):
        log(f"  Окружение найдено и работает: {VENV_DIR}")
        return EXIT_OK

    if VENV_DIR.exists():
        log("  Окружение повреждено — пересоздаю...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    log("  Создаю .venv (первый запуск, обычно 10-20 секунд)...")
    rc, output = run_logged([sys.executable, "-m", "venv", str(VENV_DIR)], timeout=600)
    if rc != 0 or not venv_python().exists():
        log("")
        log("  [ОШИБКА] Не удалось создать виртуальное окружение.")
        log("  Частые причины:")
        log("    * Python установлен из Microsoft Store без модуля venv;")
        log("    * нет прав на запись в папку проекта (распакуйте, например, в C:\\LSP_Mapper);")
        log("    * антивирус блокирует создание файлов.")
        if output:
            for line in output.splitlines()[-15:]:
                log(f"  | {line}")
        return EXIT_VENV

    log("  Готово.")
    return EXIT_OK


def ensure_dependencies(options: argparse.Namespace) -> int:
    section("[3/5] Зависимости (PySide6, pyperclip)")
    python = venv_python()
    wanted = requirements_hash()
    installed = read_stamp()

    if options.reinstall:
        log("  Запрошена переустановка (--reinstall).")
        need_install = True
    elif wanted != installed:
        log("  requirements.txt изменился (или окружение новое) — нужна установка.")
        need_install = True
    elif not imports_ok(python):
        log("  Модули не импортируются — переустанавливаю.")
        need_install = True
    else:
        log("  Всё уже установлено, скачивание не требуется.")
        return EXIT_OK

    log("  Обновляю pip/setuptools/wheel...")
    run_logged([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                "--upgrade", "pip", "setuptools", "wheel"], timeout=900)

    log("  Устанавливаю зависимости из requirements.txt (нужен интернет, 1-3 минуты)...")
    rc, output = run_logged(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "--upgrade", "-r", str(REQUIREMENTS)],
        timeout=1800,
    )

    if rc != 0 or not imports_ok(python):
        log("")
        log("  [ОШИБКА] Зависимости не установились.")
        log("  Что можно проверить:")
        log("    * интернет / VPN / прокси (pip качает с pypi.org);")
        log("    * запустите:  run_mapper.bat --repair-venv");
        log(f"    * полный журнал: {SETUP_LOG}")
        for line in output.splitlines()[-25:]:
            log(f"  | {line}")
        err = import_error_text(python)
        if err:
            log("  --- ошибка импорта ---")
            for line in err.splitlines()[-10:]:
                log(f"  | {line}")
        return EXIT_DEPS

    write_stamp(wanted)
    log("  Зависимости установлены и проверены.")
    return EXIT_OK


def describe_environment() -> None:
    log("")
    log("  Состояние окружения:")
    log(f"    Python:            {'.'.join(str(p) for p in sys.version_info[:3])}")
    log(f"    Папка проекта:     {ROOT}")
    log(f"    Виртуальное окр.:  {VENV_DIR} ({'да' if venv_python().exists() else 'нет'})")
    log(f"    PySide6/pyperclip: {'установлены' if imports_ok(venv_python()) else 'НЕ установлены'}")
    config = ROOT / "user_config.json"
    log(f"    Калибровка:        {'есть (' + str(config) + ')' if config.exists() else 'ещё не выполнялась'}")
    log(f"    Журнал установки:  {SETUP_LOG}")
    log(f"    Журнал программы:  {APP_LOG}")


def launch_app(options: argparse.Namespace) -> int:
    section("[4/5] Запуск приложения")
    python = venv_python()
    pythonw = venv_pythonw()
    log(f"  Интерпретатор: {pythonw.name}")

    READY_MARKER.parent.mkdir(parents=True, exist_ok=True)
    if READY_MARKER.exists():
        try:
            READY_MARKER.unlink()
        except Exception:  # noqa: BLE001
            pass

    if options.debug:
        log("  Режим отладки: приложение работает в этом окне, логи выводятся ниже.")
        log("  Закройте приложение, чтобы вернуться в консоль.")
        log("")
        try:
            return_code = subprocess.call(
                [str(python), str(MAIN_SCRIPT), "--debug"], cwd=str(ROOT)
            )
        except Exception as exc:  # noqa: BLE001
            log(f"  [ОШИБКА] Не удалось запустить приложение: {exc}")
            return EXIT_APP
        log("")
        log(f"  Приложение завершилось с кодом {return_code}.")
        if return_code != 0:
            show_logs_tail("журнал программы", APP_LOG, 40)
            return EXIT_APP
        return EXIT_OK

    cmd = [str(pythonw), str(MAIN_SCRIPT)]
    creationflags = 0
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            close_fds=True,
            creationflags=creationflags,
            start_new_session=not IS_WINDOWS,
            # Отвязываем окно приложения от консоли launcher-а: иначе консоль
            # (и пайпы) держатся открытыми, пока работает оверлей.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"  [ОШИБКА] Не удалось запустить процесс: {exc}")
        return EXIT_APP

    log("  Ожидаю готовности окна...")
    deadline = time.monotonic() + options.start_timeout
    while time.monotonic() < deadline:
        if READY_MARKER.exists():
            section("[5/5] Готово")
            log("  Приложение запущено. Окно оверлея должно быть на экране.")
            log(f"  Журнал работы: {APP_LOG}")
            log("")
            return EXIT_OK
        code = process.poll()
        if code is not None:
            log(f"  Процесс завершился (код {code}) до появления окна.")
            break
        time.sleep(0.2)

    log("")
    log("  [ОШИБКА] Окно не появилось.")
    show_logs_tail("журнал программы", APP_LOG, 40)
    show_logs_tail("журнал установки", SETUP_LOG, 20)
    log("  Что попробовать:")
    log("    1) run_mapper.bat --debug   — запуск с консолью и подробным логом;")
    log("    2) run_mapper.bat --repair-venv — пересоздать окружение заново;")
    log("    3) проверить, что путь к папке без кириллицы и в нём есть права на запись.")
    return EXIT_APP


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bootstrap",
        description="Подготовка окружения и запуск LSP Mapper Assist",
    )
    parser.add_argument("--debug", action="store_true", help="запустить приложение в консоли с подробным логом")
    parser.add_argument("--reinstall", action="store_true", help="принудительно переустановить зависимости")
    parser.add_argument("--repair-venv", action="store_true", help="удалить .venv и создать заново")
    parser.add_argument("--check-only", action="store_true", help="только подготовить окружение, не запускать")
    parser.add_argument("--start-timeout", type=float, default=20.0, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _init_console()
    options = parse_args(argv if argv is not None else sys.argv[1:])

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        section("LSP Mapper Assist — подготовка окружения")
        log(f"  Время: {datetime.now():%Y-%m-%d %H:%M:%S}")
        log(f"  Папка: {ROOT}")
        log(f"  Ключи: {' '.join(argv if argv is not None else sys.argv[1:]) or 'нет'}")

        for step in (check_python, lambda: ensure_venv(options), lambda: ensure_dependencies(options)):
            code = step()
            if code != EXIT_OK:
                log("")
                log(f"  Подготовка прервана (код {code}).")
                return code

        describe_environment()

        if options.check_only:
            section("Проверка завершена")
            log("  Окружение готово. Запустите run_mapper.bat без ключей, чтобы открыть оверлей.")
            return EXIT_OK

        return launch_app(options)
    except KeyboardInterrupt:
        log("  Прервано пользователем.")
        return EXIT_UNEXPECTED
    except Exception:  # noqa: BLE001
        log("  [ОШИБКА] Непредвиденный сбой при подготовке окружения:")
        for line in traceback.format_exc().splitlines():
            log(f"  | {line}")
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
