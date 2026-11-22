"""Тёмная тема оверлея.

Только текст и символы, которые есть в Segoe UI / DejaVu: эмодзи в интерфейсе
запрещены (в части шрифтов они превращаются в «квадратики»).
"""

from __future__ import annotations

BACKGROUND = "#0b1017"
SURFACE = "#141b24"
SURFACE_ALT = "#1b2430"
BORDER = "#2a3644"
TEXT = "#e8eef6"
MUTED = "#93a4b8"
ACCENT = "#2f6fed"
ACCENT_HOVER = "#3f7ff5"
SUCCESS = "#2e9e5b"
WARNING = "#c98a1b"
DANGER = "#d05151"

STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-family: "Segoe UI", "DejaVu Sans", sans-serif;
    font-size: 12px;
}}
QLabel#titleLabel {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#hintLabel {{
    color: {MUTED};
    font-size: 11px;
}}
QLabel#statusLabel {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    color: {MUTED};
}}
QLabel#statusLabel[level="error"] {{
    color: {DANGER};
    border-color: {DANGER};
}}
QLabel#statusLabel[level="success"] {{
    color: {SUCCESS};
    border-color: {SUCCESS};
}}
QLabel#stepLabel {{
    color: {MUTED};
    font-size: 11px;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding: 8px 6px 6px 6px;
    font-weight: 600;
    color: {MUTED};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QPushButton {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 9px;
    color: {TEXT};
}}
QPushButton:hover {{
    background-color: #223041;
    border-color: #3a4b5f;
}}
QPushButton:pressed {{
    background-color: #101821;
}}
QPushButton:disabled {{
    color: #5b6b7d;
    border-color: #202a36;
}}
QPushButton#primaryButton {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#successButton {{
    background-color: {SUCCESS};
    border-color: {SUCCESS};
    font-weight: 600;
}}
QPushButton#successButton:disabled {{
    background-color: #1d3327;
    border-color: #274634;
    color: #6f8a79;
}}
QPushButton#primaryButton:disabled {{
    background-color: #1b2a44;
    border-color: #22375a;
    color: #6f8299;
}}
QPushButton#arrowButton {{
    font-size: 15px;
    min-width: 34px;
    min-height: 28px;
}}
QPushButton#stepButton {{
    font-size: 11px;
    padding: 3px 6px;
}}
QPushButton#stepButton:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background-color: #0e151d;
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 6px;
    min-height: 20px;
    selection-background-color: {ACCENT};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px;
    border: none;
    background: transparent;
}}
QDoubleSpinBox[pending="true"] {{
    border: 1px solid {WARNING};
    background-color: #1a1508;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}
QCheckBox, QRadioButton {{
    spacing: 6px;
    color: {TEXT};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    top: -1px;
    padding: 6px;
}}
QTabBar::tab {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 10px;
    margin-right: 2px;
    color: {MUTED};
}}
QTabBar::tab:selected {{
    background: {SURFACE_ALT};
    color: {TEXT};
}}
QScrollArea {{
    border: none;
}}
"""
