"""Тесты инфраструктуры: логирование, launcher, калибровочный поток и модульная структура UI."""

from __future__ import annotations

import ast
import logging
import re
import sys
import threading
from pathlib import Path

import pytest

from mapper_assist import logger as app_logger
from mapper_assist.automation import FallbackInputBackend, PanelAutomator
from mapper_assist.logger import get_logger, mark_session_ready, setup_logging
from mapper_assist.ui.calibration_flow import CalibrationFlow
from mapper_assist.ui.threads import MacroRunner
from mapper_assist.models import CALIBRATION_TARGETS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = PROJECT_ROOT / "mapper_assist" / "ui"


# --------------------------------------------------------------------------- logging
def test_setup_logging_writes_rotating_file(tmp_path: Path) -> None:
    app_logger._LOGGING_CONFIGURED = False  # noqa: SLF001 — принудительная переинициализация
    log_file = setup_logging(log_dir=tmp_path, force_reconfigure=True)

    assert log_file.exists()
    assert log_file.parent == tmp_path

    get_logger("mapper_assist.test").info("Проверка записи в лог 42")
    for handler in logging.getLogger("mapper_assist").handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "Проверка записи в лог 42" in content
    assert "| INFO" in content

    # Ротация настроена: файл не вырастет бесконечно
    rotating = [
        h
        for h in logging.getLogger("mapper_assist").handlers
        if hasattr(h, "maxBytes") and getattr(h, "backupCount", 0) >= 1
    ]
    assert rotating, "Ожидался RotatingFileHandler с резервными копиями"


def test_unhandled_exception_is_logged(tmp_path: Path) -> None:
    import sys

    setup_logging(log_dir=tmp_path, force_reconfigure=True)
    log_file = app_logger.get_log_file_path()

    try:
        raise RuntimeError("Специальная тестовая ошибка макроса")
    except RuntimeError:
        exc_info = sys.exc_info()
        sys.excepthook(*exc_info)  # type: ignore[arg-type]

    for handler in logging.getLogger("mapper_assist").handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "Специальная тестовая ошибка макроса" in content
    assert "CRITICAL" in content


def test_session_ready_marker(tmp_path: Path) -> None:
    setup_logging(log_dir=tmp_path, force_reconfigure=True)
    marker = mark_session_ready("1.0.0-test")
    assert marker is not None and marker.exists()
    assert "version=1.0.0-test" in marker.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- launcher
def test_launcher_is_ascii_and_crlf() -> None:
    """ASCII + CRLF: .bat нельзя ломать кодировкой или LF — иначе окно закрывается мгновенно."""
    data = (PROJECT_ROOT / "run_mapper.bat").read_bytes()
    data.decode("ascii")  # бросит UnicodeDecodeError, если появится не-ASCII
    assert data.count(b"\r\n") > 30
    assert data.count(b"\n") == data.count(b"\r\n"), "В .bat не должно быть одиночных LF"
    assert not data.startswith(b"\xef\xbb\xbf"), "BOM в начале .bat ломает cmd"


def test_launcher_never_closes_silently() -> None:
    source = (PROJECT_ROOT / "run_mapper.bat").read_text(encoding="ascii")
    # На каждую ошибку — пауза, иначе окно закроется до того, как пользователь прочитает текст
    error_blocks = re.findall(r"\[ERROR\][\s\S]{0,400}?exit /b", source)
    assert error_blocks, "В launcher-е нет блоков обработки ошибок"
    for block in error_blocks:
        assert "pause" in block, f"Блок ошибки без pause:\n{block}"


def test_launcher_delegates_to_bootstrap() -> None:
    source = (PROJECT_ROOT / "run_mapper.bat").read_text(encoding="ascii")
    assert "tools\\bootstrap.py" in source
    assert "pause" in source
    assert "%*" in source, "Аргументы (--debug, --reinstall...) должны передаваться дальше"
    assert (PROJECT_ROOT / "tools" / "bootstrap.py").exists()
    # Никакой сложной логики в batch: ни циклов, ни goto, ни delayed expansion
    assert "goto " not in source.lower()
    assert "for /f" not in source.lower()
    assert "setlocal EnableDelayedExpansion" not in source


def test_bootstrap_covers_required_steps() -> None:
    source = (PROJECT_ROOT / "tools" / "bootstrap.py").read_text(encoding="utf-8")
    for step in (
        "-m", "venv",          # создание окружения
        "pip", "install",      # установка зависимостей
        "requirements.txt",
        "session_ready.txt",   # контроль успешного старта GUI
        "setup.log",
        "mapper_assist.log",
        "--repair-venv",
        "--check-only",
        "--debug",
    ):
        assert step in source, f"bootstrap.py не содержит шага: {step}"


def test_bootstrap_help_runs_without_side_effects(tmp_path: Path) -> None:
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "bootstrap.py"), "--help"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    assert proc.returncode == 0
    output = proc.stdout.decode("utf-8", "replace")
    assert "--repair-venv" in output and "--check-only" in output


def test_bootstrap_helpers(tmp_path: Path, monkeypatch) -> None:
    import importlib

    bootstrap = importlib.import_module("tools.bootstrap")

    assert bootstrap.requirements_hash() == bootstrap.requirements_hash()
    assert len(bootstrap.requirements_hash()) == 32

    sample = tmp_path / "sample.log"
    sample.write_text("\n".join(f"line {i}" for i in range(50)), encoding="utf-8")
    tail = bootstrap.tail_of(sample, 5)
    assert tail.splitlines() == [f"line {i}" for i in range(45, 50)]

    assert bootstrap.tail_of(tmp_path / "missing.log") == ""

    options = bootstrap.parse_args(["--debug", "--repair-venv", "--check-only"])
    assert options.debug and options.repair_venv and options.check_only
    assert options.start_timeout > 0

    monkeypatch.setattr(bootstrap, "STAMP_FILE", tmp_path / "stamp")
    bootstrap.write_stamp("abc123")
    assert bootstrap.read_stamp() == "abc123"


# --------------------------------------------------------------------------- калибровка
@pytest.fixture(scope="module")
def qt_core_app():
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def test_calibration_flow_queue_and_capture(qt_core_app) -> None:
    flow = CalibrationFlow(cursor_provider=lambda: (321, 654), hotkey_name_provider=lambda: "F9")
    captured: list[tuple[str, int, int]] = []
    banners: list[str] = []
    flow.point_captured.connect(lambda t, x, y: captured.append((t, x, y)))
    flow.banner_text_changed.connect(banners.append)

    finished: list[bool] = []
    flow.finished.connect(lambda: finished.append(True))

    flow.start_full()
    assert flow.is_active
    assert flow.remaining == len(CALIBRATION_TARGETS)
    assert "F9" in banners[-1]

    flow.capture_now()
    assert captured == [(CALIBRATION_TARGETS[0], 321, 654)]
    assert flow.remaining == len(CALIBRATION_TARGETS) - 1

    flow.cancel()
    assert not flow.is_active
    assert not finished


def test_calibration_flow_finishes_on_last_point(qt_core_app) -> None:
    flow = CalibrationFlow(cursor_provider=lambda: (5, 6), hotkey_name_provider=lambda: "Alt+C")
    finished: list[bool] = []
    flow.finished.connect(lambda: finished.append(True))

    flow.start_single("rz")
    flow.capture_now()

    assert finished == [True]
    assert not flow.is_active


# --------------------------------------------------------------------------- макросы
def test_macro_runner_serializes_tasks(qt_core_app) -> None:
    runner = MacroRunner()
    started = threading.Event()
    release = threading.Event()

    def slow_task() -> tuple[str, object]:
        started.set()
        release.wait(timeout=5)
        return "готово", []

    assert runner.run(slow_task, label="тест") is True
    assert started.wait(timeout=5), "Макрос не стартовал"

    # Пока первый макрос выполняется, второй должен быть отклонён
    assert runner.run(lambda: ("второй", []), label="тест-2") is False

    release.set()
    for _ in range(100):
        if not runner.is_busy:
            break
        threading.Event().wait(0.02)


def test_default_panel_automator_uses_fallback_on_linux() -> None:
    automator = PanelAutomator()
    assert isinstance(automator.backend, FallbackInputBackend)


# --------------------------------------------------------------------------- структура UI
def _class_members(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            members: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    members.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        if isinstance(target, ast.Name):
                            members.add(target.id)
                        elif (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            members.add(target.attr)
                elif isinstance(sub, ast.AnnAssign):
                    target = sub.target
                    if isinstance(target, ast.Name):
                        members.add(target.id)
                    elif (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        members.add(target.attr)
            return members
    raise AssertionError(f"Класс {class_name} не найден в {path}")


@pytest.mark.parametrize(
    ("tab_attr", "module", "class_name"),
    [
        ("movement", "tabs/movement_tab.py", "MovementTab"),
        ("join_tab", "tabs/join_tab.py", "JoinTab"),
        ("calib_tab", "tabs/calibration_tab.py", "CalibrationTab"),
        ("field_box", "widgets.py", "CoordinatesBox"),
        ("calibration_flow", "calibration_flow.py", "CalibrationFlow"),
        ("macro_runner", "threads.py", "MacroRunner"),
    ],
)
def test_main_window_uses_only_existing_tab_members(tab_attr: str, module: str, class_name: str) -> None:
    members = _class_members(UI_DIR / module, class_name)
    tree = ast.parse((UI_DIR / "main_window.py").read_text(encoding="utf-8"))

    used: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
            and node.value.attr == tab_attr
        ):
            used.add(node.attr)

    missing = sorted(used - members)
    assert not missing, f"main_window.py обращается к несуществующим членам {class_name}: {missing}"


def test_ui_modules_are_split_by_responsibility() -> None:
    files = {p.name for p in UI_DIR.rglob("*.py")}
    for expected in {
        "main_window.py",
        "calibration_flow.py",
        "threads.py",
        "widgets.py",
        "gizmo_widget.py",
        "settings_dialog.py",
        "styles.py",
        "movement_tab.py",
        "join_tab.py",
        "calibration_tab.py",
    }:
        assert expected in files, f"Отсутствует модуль {expected}"

    main_window_lines = len((UI_DIR / "main_window.py").read_text(encoding="utf-8").splitlines())
    assert main_window_lines < 900, "Главное окно слишком разрослось — вынесите логику в отдельные модули"


def test_automation_package_is_split() -> None:
    automation_dir = PROJECT_ROOT / "mapper_assist" / "automation"
    files = {p.name for p in automation_dir.glob("*.py")}
    assert {"__init__.py", "base.py", "win32_backend.py", "panel_automator.py", "fallback_backend.py"} <= files


# --------------------------------------------------------------------------- связи сигналов
def _declared_signals(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    signals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                targets: list[ast.expr] = []
                if isinstance(sub, ast.Assign):
                    targets = list(sub.targets)
                elif isinstance(sub, ast.AnnAssign):
                    targets = [sub.target]
                for target in targets:
                    if isinstance(target, ast.Name) and isinstance(sub.value, ast.Call):
                        func = sub.value.func
                        if isinstance(func, ast.Name) and func.id == "Signal":
                            signals.add(target.id)
    return signals


def test_click_handlers_do_not_forward_checkbox_flag_to_signals() -> None:
    """clicked(bool) нельзя подключать напрямую к .emit сигнала без аргументов — Qt передаст bool."""
    for path in (UI_DIR / "tabs").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert ".clicked.connect(self." not in source or ".emit)" not in source, (
            f"{path.name}: обработчик clicked должен явно вызывать emit() через lambda"
        )


def test_all_tab_signals_are_connected_in_main_window() -> None:
    window_source = (UI_DIR / "main_window.py").read_text(encoding="utf-8")

    for module, class_name in (
        ("tabs/movement_tab.py", "MovementTab"),
        ("tabs/join_tab.py", "JoinTab"),
        ("tabs/calibration_tab.py", "CalibrationTab"),
    ):
        for signal in _declared_signals(UI_DIR / module, class_name):
            assert f".{signal}.connect(" in window_source, (
                f"Сигнал {class_name}.{signal} объявлен, но не подключён в главном окне"
            )


def test_main_window_members_exist() -> None:
    members = _class_members(UI_DIR / "main_window.py", "MapperMainWindow")
    tree = ast.parse((UI_DIR / "main_window.py").read_text(encoding="utf-8"))

    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            used.add(node.attr)

    qt_window_api = {
        "adjustSize", "move", "setCentralWidget", "setMaximumWidth", "setMinimumWidth",
        "setStyleSheet", "setWindowFlags", "setWindowOpacity", "setWindowTitle", "show",
        "pos", "close", "hide", "setFixedWidth",
    }
    missing = sorted(
        name for name in used - members - qt_window_api if not name.startswith("__")
    )
    assert not missing, f"Главное окно использует необъявленные атрибуты: {missing}"


def test_launcher_labels_are_consistent() -> None:
    import re

    source = (PROJECT_ROOT / "run_mapper.bat").read_text(encoding="utf-8")
    labels = set(re.findall(r"^:(\w+)", source, re.M))
    gotos = set(re.findall(r"goto\s+(\w+)", source, re.I)) - {"eof"}
    calls = set(re.findall(r"call\s+:(\w+)", source, re.I))

    assert not (gotos - labels), f"goto на несуществующие метки: {gotos - labels}"
    assert not (calls - labels), f"call на несуществующие метки: {calls - labels}"

    depth = 0
    for line in source.splitlines():
        stripped = re.sub(r'"[^"]*"', "", line)
        stripped = re.sub(r"rem\b.*", "", stripped, flags=re.I)
        depth += stripped.count("(") - stripped.count(")")
        assert depth >= 0, f"Лишняя закрывающая скобка в строке: {line}"
    assert depth == 0, "Несбалансированные скобки в run_mapper.bat"
