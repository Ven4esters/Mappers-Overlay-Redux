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
QPushButton:disabled {{ color: #55627a; border-color: #222c40; }}
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
QStatusBar {{ background: {BACKGROUND}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {SURFACE_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
}}
"""
