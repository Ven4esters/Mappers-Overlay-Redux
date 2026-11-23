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
QLabel[role="badge"], QLabel[role="badgeOk"] {{
    color: {MUTED};
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 3px 9px;
}}
QLabel[role="badgeOk"] {{ color: {SUCCESS}; border-color: #235c45; }}
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
QPushButton[role="danger"] {{
    background: transparent;
    border: 1px solid {DANGER_EDGE};
    color: {DANGER_TEXT};
}}
QPushButton[role="danger"]:hover {{ background: rgba(239, 68, 68, 0.12); border-color: {ERROR}; }}
QPushButton[role="danger"]:pressed {{ background: rgba(239, 68, 68, 0.2); }}
QPushButton[role="danger"]:disabled {{
    color: #5a3a42;
    border-color: #33222a;
    background: transparent;
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
    padding: 6px 8px;
    min-height: 20px;
    selection-background-color: #2563eb;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ color: #55627a; border-color: #222c40; }}
QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {SURFACE_RAISED};
    border: 1px solid #2c3a55;
    border-radius: 8px;
    padding: 6px 8px;
    min-height: 20px;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
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
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {SURFACE_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
}}
"""
