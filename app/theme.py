"""Dark-navy visual theme (UIX-friendly QSS). / Тёмная синяя тема (UIX-QSS).

Palette / Палитра:
    bg        #0B1220   window background
    panel     #111B2E   sidebars, toolbars
    card      #16233C   cards, inputs
    card_alt  #1B2B4A   hover states
    border    #25365A   subtle separators
    accent    #4F7DFF   primary actions, focus ring
    accent_hi #6E92FF   accent hover
    text      #E8EDF7   primary text
    text_dim  #8A99B8   secondary text
    success   #34D399
    danger    #F87171
    warning   #FBBF24
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

COLORS: dict[str, str] = {
    "bg": "#0B1220",
    "panel": "#111B2E",
    "card": "#16233C",
    "card_alt": "#1B2B4A",
    "border": "#25365A",
    "accent": "#4F7DFF",
    "accent_hi": "#6E92FF",
    "text": "#E8EDF7",
    "text_dim": "#8A99B8",
    "success": "#34D399",
    "danger": "#F87171",
    "warning": "#FBBF24",
}

QSS: str = f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 13px; }}
QMainWindow, QDialog {{ background: {COLORS['bg']}; }}
QWidget {{ color: {COLORS['text']}; }}

/* --- panels & cards --- */
#Sidebar {{ background: {COLORS['panel']}; border-right: 1px solid {COLORS['border']}; }}
#Card {{ background: {COLORS['card']}; border: 1px solid {COLORS['border']}; border-radius: 12px; }}
#EmptyState {{ background: transparent; }}

/* --- typography --- */
QLabel {{ color: {COLORS['text']}; background: transparent; }}
#Title {{ font-size: 26px; font-weight: 700; letter-spacing: 0.2px; }}
#Subtitle {{ color: {COLORS['text_dim']}; font-size: 13px; }}
#SectionLabel {{ color: {COLORS['text_dim']}; font-size: 11px; font-weight: 700;
                letter-spacing: 1.4px; text-transform: uppercase; }}
#Dim {{ color: {COLORS['text_dim']}; }}

/* --- buttons --- */
QPushButton {{ background: {COLORS['card']}; color: {COLORS['text']};
               border: 1px solid {COLORS['border']}; border-radius: 8px;
               padding: 8px 16px; }}
QPushButton:hover {{ background: {COLORS['card_alt']}; border-color: {COLORS['accent']}; }}
QPushButton:pressed {{ background: {COLORS['card_alt']}; }}
QPushButton:focus {{ outline: none; border: 2px solid {COLORS['accent']}; padding: 7px 15px; }}
QPushButton:disabled {{ color: {COLORS['text_dim']}; background: {COLORS['panel']};
                        border-color: {COLORS['border']}; }}

QPushButton#Primary {{ background: {COLORS['accent']}; color: #FFFFFF; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {COLORS['accent_hi']}; }}
QPushButton#Primary:disabled {{ background: {COLORS['card']}; color: {COLORS['text_dim']}; }}

QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; }}
QPushButton#Ghost:hover {{ background: {COLORS['card']}; border-color: {COLORS['border']}; }}

QPushButton#Danger {{ background: transparent; color: {COLORS['danger']}; border: 1px solid {COLORS['danger']}; }}
QPushButton#Danger:hover {{ background: rgba(248, 113, 113, 0.12); }}

/* --- inputs --- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {COLORS['card']}; border: 1px solid {COLORS['border']};
    border-radius: 8px; padding: 8px 10px; selection-background-color: {COLORS['accent']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {COLORS['accent']}; padding: 7px 9px;
}}
QComboBox QAbstractItemView {{ background: {COLORS['card']}; border: 1px solid {COLORS['border']};
                               selection-background-color: {COLORS['accent']}; }}

/* --- list --- */
QListWidget, QListView {{ background: {COLORS['card']}; border: 1px solid {COLORS['border']};
                          border-radius: 10px; padding: 6px; outline: 0; }}
QListWidget::item {{ border-radius: 8px; padding: 8px 10px; }}
QListWidget::item:hover {{ background: {COLORS['card_alt']}; }}
QListWidget::item:selected {{ background: {COLORS['accent']}; color: #FFFFFF; }}

/* --- progress --- */
QProgressBar {{ background: {COLORS['card']}; border: 1px solid {COLORS['border']};
                border-radius: 7px; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 6px; }}

/* --- misc --- */
QStatusBar {{ background: {COLORS['panel']}; border-top: 1px solid {COLORS['border']}; color: {COLORS['text_dim']}; }}
QToolTip {{ background: {COLORS['card']}; color: {COLORS['text']};
            border: 1px solid {COLORS['accent']}; border-radius: 6px; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {COLORS['accent']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {COLORS['border']}; border-radius: 5px; min-width: 30px; }}
"""


def apply_theme(app: QApplication) -> None:
    """Apply palette + QSS to the application. / Применить палитру и QSS."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["card"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["card_alt"]))
    palette.setColor(QPalette.ToolTipBase, QColor(COLORS["card"]))
    palette.setColor(QPalette.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["card"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.PlaceholderText, QColor(COLORS["text_dim"]))
    app.setPalette(palette)
    app.setStyleSheet(QSS)
