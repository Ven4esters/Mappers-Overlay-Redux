"""Тёмная тема и палитра интерфейса."""

from __future__ import annotations

from typing import Final

BACKGROUND: Final = "#0e131c"
SURFACE: Final = "#161d2b"
SURFACE_RAISED: Final = "#1d2739"
BORDER: Final = "#26324a"
TEXT: Final = "#e6ebf5"
MUTED: Final = "#8a97ad"
ACCENT: Final = "#3b82f6"
WARNING: Final = "#f5b942"
ERROR: Final = "#ef4444"
SUCCESS: Final = "#34d399"
TEXT_DISABLED: Final = "#3d475a"
# Цвет выключенного элемента: заметно тусклее обычного текста, но не «дыра» на экране.
PANEL_DISPLAY: Final = "#0f1521"
# Фон полей-показаний (координаты): темнее карточки, чтобы число читалось как данные.
DANGER_EDGE: Final = "#7f2d2d"
DANGER_TEXT: Final = "#f87171"
# Красный текст для опасных действий: читается на тёмном, но не «кричит».

APP_QSS: Final = f"""
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QWidget#central {{ background: transparent; }}
QTabWidget {{ background: transparent; }}
QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#header {{ background: {BACKGROUND}; border: none; }}
QLabel[role="cardTitle"] {{ color: {MUTED}; font-size: 11px; font-weight: 600; }}
QLabel[role="poseField"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="poseValue"] {{ font-family: "Consolas", "Cascadia Mono", monospace; font-size: 16px; }}
QLabel[role="poseDisplay"] {{
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 16px;
    background: {PANEL_DISPLAY};
    border: 1px solid #1e2739;
    border-radius: 6px;
    padding: 3px 8px;
}}
QLabel[role="poseDisplay"][empty="true"] {{ color: #4f5c73; }}
QLabel[role="hint"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="info"] {{ background: transparent; }}
QLabel[role="info"]:hover {{ background: rgba(255, 255, 255, 0.08); border-radius: 7px; }}
QLabel[role="rowName"] {{
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 14px;
    color: {TEXT};
}}
QLabel[role="rowSize"] {{
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    color: {MUTED};
}}
QLabel[role="badge"], QLabel[role="badgeOk"], QPushButton[role="badge"] {{
    color: {MUTED};
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 3px 9px;
}}
QLabel[role="badgeOk"] {{ color: {SUCCESS}; border-color: #235c45; }}
/* «Мини» — та же пилюля, что и бейдж калибровки: одна высота и один радиус. */
QPushButton[role="badge"] {{ color: {TEXT}; }}
QPushButton[role="badge"]:hover {{
    background: #2f3d5e;
    border-color: #4a6ea8;
    color: #ffffff;
}}
QPushButton[role="badge"]:pressed {{ background: #1d2740; }}
QPushButton[role="badge"]:disabled {{ color: {TEXT_DISABLED}; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="warn"] {{ color: {WARNING}; }}
QLabel[role="error"] {{ color: {ERROR}; }}
QLabel[role="ok"] {{ color: {SUCCESS}; }}
QLabel[role="appTitle"] {{ font-size: 17px; font-weight: 700; }}
QLabel[role="stepLabel"] {{
    color: {MUTED};
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 13px;
}}
QPushButton {{
    background: {SURFACE_RAISED};
    border: 1px solid #2c3a55;
    border-radius: 8px;
    padding: 8px 14px;
}}
QPushButton:hover {{ background: #243050; }}
QPushButton:pressed {{ background: #172033; }}
QPushButton:disabled {{
    color: {TEXT_DISABLED};
    background: rgba(22, 29, 43, 0.45);
    border-color: #1b2333;
}}
QPushButton[role="primary"] {{
    background: #2563eb;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT}; }}
QPushButton[role="primary"]:disabled {{
    background: #1b2740;
    border-color: #26324a;
    color: #55627a;
}}
/* «Прервать» — аварийная остановка: в покое серая кнопка, во время обмена красная. */
QPushButton[role="abort"] {{
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    color: #c2cbdb;
    padding: 4px 12px;
}}
QPushButton[role="abort"]:hover {{ background: #243050; color: {TEXT}; }}
QPushButton[role="abort"]:enabled {{
    background: rgba(239, 68, 68, 0.8);
    border: 1px solid {ERROR};
    color: #ffffff;
}}
QPushButton[role="abort"]:enabled:hover {{ background: {ERROR}; }}
QPushButton[role="abort"]:enabled:pressed {{ background: #dc2626; }}
QPushButton[role="danger"] {{
    background: rgba(239, 68, 68, 0.16);
    border: 1px solid {DANGER_EDGE};
    color: #fecaca;
}}
QPushButton[role="danger"]:hover {{ background: rgba(239, 68, 68, 0.26); border-color: {ERROR}; }}
QPushButton[role="danger"]:pressed {{ background: rgba(239, 68, 68, 0.34); }}
QPushButton[role="danger"]:disabled {{
    color: #4a3a3e;
    border-color: #33222a;
    background: transparent;
}}
QPushButton[role="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: #b9c4d6;
    padding: 4px 8px;
    font-size: 12px;
}}
QPushButton[role="ghost"]:hover {{ color: {TEXT}; background: rgba(255, 255, 255, 0.06); }}
/* Выключенная «Выбрать» — это уже выбранный предмет: белый текст и лёгкая подложка. */
QPushButton[role="ghost"]:disabled {{
    color: #e6ebf3;
    background: rgba(148, 163, 184, 0.16);
    border-radius: 8px;
}}
QPushButton[role="icon"] {{
    background: transparent;
    border: 1px solid transparent;
    padding: 0;
    border-radius: 8px;
}}
QPushButton[role="icon"]:hover {{ background: rgba(255, 255, 255, 0.08); }}
QPushButton[role="icon"]:disabled {{ background: transparent; }}
/* Значок удаления: красный рисунок без рамки, красный фон — только при наведении. */
QPushButton[severity="danger"][role="icon"] {{
    background: transparent;
    border: 1px solid transparent;
}}
QPushButton[severity="danger"][role="icon"]:hover {{ background: rgba(239, 68, 68, 0.16); }}
QPushButton[role="clear"] {{
    background: transparent;
    border: 1px solid rgba(239, 68, 68, 0.45);
    color: {DANGER_TEXT};
}}
QPushButton[role="clear"]:hover {{
    border-color: {ERROR};
    color: #fecaca;
    background: rgba(239, 68, 68, 0.12);
}}
QPushButton[role="clear"]:disabled {{ color: {TEXT_DISABLED}; border-color: #1b2333; }}
QListWidget#sizesList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#sizesList::item {{
    border-radius: 8px;
    margin: 1px 0;
}}
QListWidget#sizesList::item:hover {{ background: rgba(255, 255, 255, 0.04); }}
QListWidget#sizesList::item:selected {{
    background: rgba(59, 130, 246, 0.18);
    color: {TEXT};
}}
QPushButton[role="small"] {{
    padding: 4px 10px;
    min-height: 0;
    font-size: 12px;
}}
/* Опасное действие с компактным размером: свойство severity не спорит с ролью. */
QPushButton[severity="danger"] {{
    border: 1px solid {DANGER_EDGE};
    color: {DANGER_TEXT};
}}
QPushButton[severity="danger"]:hover {{
    background: rgba(239, 68, 68, 0.12);
    border-color: {ERROR};
}}
QPushButton[severity="danger"]:pressed {{ background: rgba(239, 68, 68, 0.2); }}
QPushButton[severity="danger"]:disabled {{
    color: #5a3a42;
    border-color: #33222a;
    background: rgba(22, 29, 43, 0.45);
}}
QPushButton[role="arrow"] {{
    font-size: 20px;
    padding: 0;
    min-width: 62px;
    min-height: 48px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    background: #101724;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 8px 18px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QLineEdit {{
    background: {SURFACE_RAISED};
    border: 1px solid #2c3a55;
    border-radius: 8px;
    padding: 8px 12px;
    min-height: 20px;
    selection-background-color: #2563eb;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ color: #55627a; border-color: #222c40; }}
QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {SURFACE_RAISED};
    border: 1px solid #2c3a55;
    border-radius: 8px;
    padding: 8px 12px;
    min-height: 20px;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
/* Поле ввода внутри выпадающего списка — часть списка, а не отдельное поле:
   общая рамка и отступы QLineEdit внутри него обрезали текст и прятали курсор. */
QComboBox QLineEdit {{
    background: transparent;
    border: none;
    padding: 0 4px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    selection-background-color: #2563eb;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #2c3a55;
    background: {SURFACE_RAISED};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #243050;
    border-radius: 4px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: #33456b; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #243050; border-radius: 4px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ background: {BACKGROUND}; }}
QLabel#status {{ font-size: 12px; }}
QLabel#status[role="muted"] {{ color: #a0a0a0; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {SURFACE_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
}}
"""
