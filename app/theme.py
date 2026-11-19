"""Dark-navy visual theme (UIX-friendly QSS). / Тёмная синяя тема (UIX-QSS).

Palette / Палитра:
    bg        #0B1220   window background
    panel     #111B2E   sidebars, toolbars
    card      #16233C   cards, inputs
    card_alt  #1B2B4A   hover states
    border    #25365A   subtle separators
    accent    #4F7DFF   primary actions, focus ring
    accent_hi #6E92FF   accent hover
    accent_soft rgba(79,125,255,41)  subtle highlight fill (~16% alpha)
    text      #E8EDF7   primary text
    text_dim  #A8B8DC   secondary text
    success   #34D399
    danger    #F87171
    warning   #FBBF24
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.paths import ASSETS_DIR

COLORS: dict[str, str] = {
    "bg": "#0B1220",
    "panel": "#111B2E",
    "card": "#16233C",
    "card_alt": "#1B2B4A",
    "border": "#32456F",
    "accent": "#4F7DFF",
    "accent_hi": "#6E92FF",
    "accent_soft": "rgba(79, 125, 255, 41)",
    "text": "#E8EDF7",
    "text_dim": "#A8B8DC",
    "success": "#34D399",
    "danger": "#F87171",
    "warning": "#FBBF24",
}

_ICONS = ASSETS_DIR / "icons"
_CHEVRON = (_ICONS / "chevron-down.svg").as_posix()
_CHECK = (_ICONS / "check.svg").as_posix()

QSS: str = f"""
* {{ font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif; font-size: 14px; }}
QMainWindow, QDialog {{ background: {COLORS['bg']}; }}
QWidget {{ color: {COLORS['text']}; background: transparent; }}

/* --- panels & cards --- */
#Sidebar {{ background: {COLORS['panel']}; border-right: 1px solid {COLORS['border']}; }}
#Card {{ background: {COLORS['card']}; border: 1px solid {COLORS['border']}; border-radius: 12px; }}
#EmptyState {{ background: transparent; }}
#SectionHeader {{ font-size: 16px; font-weight: 700; color: #FFFFFF; }}
#AlbumName {{ font-size: 16px; font-weight: 700; color: #FFFFFF; }}

/* --- typography --- */
QLabel {{ color: {COLORS['text']}; }}
#Title {{ font-size: 26px; font-weight: 700; letter-spacing: 0.2px; }}
#Subtitle {{ color: #A4B4D8; font-size: 13px; }}
#SectionLabel {{ color: #C9D4EE; font-size: 12px; font-weight: 700;
                letter-spacing: 1.1px; text-transform: uppercase; }}
#Dim {{ color: {COLORS['text_dim']}; font-size: 12px; }}
#Hint {{ color: #A4B4D8; font-size: 12px; }}

/* --- group box --- */
QGroupBox {{ background: {COLORS['card']}; border: 1px solid {COLORS['border']};
            border-radius: 12px; margin-top: 0px; padding: 34px 14px 14px 14px; }}
QGroupBox:hover {{ border-color: #3D5180; }}
QGroupBox::title {{ subcontrol-origin: padding; subcontrol-position: top left;
                    top: 10px; left: 8px; padding: 0 6px; color: #F2F5FB;
                    font-size: 13px; font-weight: 700; letter-spacing: 0.2px; }}

/* --- buttons --- */
QPushButton {{ background: {COLORS['card']}; color: {COLORS['text']};
               border: 1px solid {COLORS['border']}; border-radius: 8px;
               padding: 8px 16px; min-height: 20px; }}
QPushButton:hover {{ background: {COLORS['card_alt']}; border-color: {COLORS['accent']}; }}
QPushButton:pressed {{ background: {COLORS['card_alt']}; }}
QPushButton:focus {{ outline: none; border: 2px solid {COLORS['accent']}; padding: 7px 15px; }}
QPushButton:disabled {{ color: {COLORS['text_dim']}; background: {COLORS['panel']};
                        border-color: {COLORS['border']}; }}

QPushButton#Primary {{ background: {COLORS['accent']}; color: #FFFFFF;
                       border: 1px solid {COLORS['accent']}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {COLORS['accent_hi']}; border-color: {COLORS['accent_hi']}; }}
QPushButton#Primary:disabled {{ background: {COLORS['card']}; border-color: {COLORS['border']};
                                color: {COLORS['text_dim']}; }}

QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; color: {COLORS['text_dim']}; }}
QPushButton#Ghost:hover {{ background: {COLORS['card']}; color: {COLORS['text']}; border-color: {COLORS['border']}; }}

QPushButton#Danger {{ background: transparent; color: {COLORS['danger']};
                      border: 1px solid {COLORS['danger']}; }}
QPushButton#Danger:hover {{ background: rgba(248, 113, 113, 31); }}

QPushButton#HotkeyRecorder {{ background: {COLORS['panel']}; border: 1px dashed {COLORS['border']};
                              border-radius: 8px; padding: 6px 18px; min-width: 96px;
                              font-size: 13px; font-weight: 600; }}
QPushButton#HotkeyRecorder:hover {{ border-color: {COLORS['accent']}; border-style: solid; }}
QPushButton#HotkeyRecorder:focus {{ border: 1px solid {COLORS['accent']}; border-style: solid;
                                    background: {COLORS['card_alt']}; }}

QPushButton#FooterButton {{ font-size: 12px; padding: 8px 6px; background: transparent;
                            border: 1px solid transparent; color: {COLORS['text_dim']}; }}
QPushButton#FooterButton:hover {{ background: {COLORS['card']}; color: {COLORS['text']};
                                  border-color: {COLORS['border']}; }}
QPushButton#NavButton {{ background: transparent; border: 1px solid transparent;
                         text-align: left; padding: 9px 12px; border-radius: 8px;
                         color: {COLORS['text_dim']}; font-size: 13px; }}
QPushButton#NavButton:hover {{ background: {COLORS['card']}; color: {COLORS['text']}; }}
QPushButton#NavButton:checked {{ background: {COLORS['accent_soft']}; color: #FFFFFF;
                                 border-color: {COLORS['accent']}; }}
QPushButton#NavButton:focus {{ outline: none; border: 2px solid {COLORS['accent']}; padding: 8px 11px; }}

/* --- segmented control --- */
QPushButton#Segmented {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
                         border-radius: 8px; padding: 7px 12px; color: {COLORS['text_dim']};
                         font-size: 12px; font-weight: 600; }}
QPushButton#Segmented:hover {{ color: {COLORS['text']}; border-color: {COLORS['accent']}; }}
QPushButton#Segmented:checked {{ background: {COLORS['accent']}; border-color: {COLORS['accent']};
                                 color: #FFFFFF; }}
QPushButton#Segmented:disabled {{ color: {COLORS['text_dim']}; border-color: {COLORS['border']}; }}

/* --- inputs --- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
    border-radius: 8px; padding: 8px 12px; min-height: 20px;
    selection-background-color: {COLORS['accent']}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {COLORS['accent']}; padding: 7px 11px; }}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{ color: {COLORS['text_dim']}; }}

/* --- combo box (dropdown) --- */
QComboBox {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
             border-radius: 8px; padding: 8px 12px; min-height: 20px;
             selection-background-color: {COLORS['accent']}; }}
QComboBox:hover {{ border-color: {COLORS['accent']}; }}
QComboBox:disabled {{ color: {COLORS['text_dim']}; background: {COLORS['panel']}; }}
QComboBox:focus {{ border: 2px solid {COLORS['accent']}; padding: 7px 11px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
                        width: 30px; border: none; }}
QComboBox::down-arrow {{ image: url("{_CHEVRON}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {COLORS['card_alt']}; color: {COLORS['text']};
                               border: 1px solid {COLORS['border']}; border-radius: 10px;
                               padding: 6px; outline: 0;
                               selection-background-color: {COLORS['accent']};
                               selection-color: #FFFFFF; }}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 4px 12px;
                                     border-radius: 6px; color: {COLORS['text']}; }}
QComboBox QAbstractItemView::item:hover {{ background: {COLORS['card']}; }}
QComboBox QAbstractItemView::item:selected {{ background: {COLORS['accent']}; color: #FFFFFF; }}

/* --- radio & checkbox --- */
QRadioButton, QCheckBox {{ spacing: 8px; color: {COLORS['text']}; background: transparent; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px;
                           border: 2px solid {COLORS['border']}; background: transparent; }}
QRadioButton::indicator:hover {{ border-color: {COLORS['accent']}; }}
QRadioButton::indicator:checked {{ border: 5px solid {COLORS['accent']};
                                   background: {COLORS['accent_hi']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
                        border: 2px solid {COLORS['border']}; background: transparent; }}
QCheckBox::indicator:hover {{ border-color: {COLORS['accent']}; }}
QCheckBox::indicator:checked {{ border-color: {COLORS['accent']}; background: {COLORS['accent']};
                                image: url("{_CHECK}"); }}
QCheckBox::indicator:disabled {{ border-color: {COLORS['border']}; background: {COLORS['panel']}; }}

/* --- list --- */
QListWidget, QListView {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
                          border-radius: 10px; padding: 6px; outline: 0; }}
QListWidget::item {{ border-radius: 8px; padding: 9px 11px; color: {COLORS['text']}; }}
QListWidget::item:hover {{ background: {COLORS['card']}; }}
QListWidget::item:selected {{ background: {COLORS['accent_soft']}; color: #FFFFFF; }}

/* --- progress --- */
QProgressBar {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']};
                border-radius: 7px; text-align: center; height: 16px;
                color: {COLORS['text']}; font-size: 12px; }}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 6px; }}

/* --- message boxes --- */
QMessageBox QPushButton {{ min-width: 88px; }}
QMessageBox QLabel {{ min-width: 260px; }}

/* --- misc --- */
QStatusBar {{ background: {COLORS['panel']}; border-top: 1px solid {COLORS['border']};
              color: {COLORS['text_dim']}; font-size: 12px; }}
QToolTip {{ background: {COLORS['card_alt']}; color: {COLORS['text']};
            border: 1px solid {COLORS['accent']}; border-radius: 6px; padding: 6px 9px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 5px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {COLORS['accent']}; }}
QScrollBar::handle:horizontal {{ background: {COLORS['border']}; height: 10px; border-radius: 5px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: {COLORS['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; image: none; }}
QScrollBar::up-arrow, QScrollBar::down-arrow, QScrollBar::left-arrow, QScrollBar::right-arrow {{
    image: none; width: 0; height: 0; }}
"""


def apply_theme(app: QApplication) -> None:
    """Apply palette + QSS to the application. / Применить палитру и QSS."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["panel"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["card"]))
    palette.setColor(QPalette.ToolTipBase, QColor(COLORS["card_alt"]))
    palette.setColor(QPalette.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["card"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.PlaceholderText, QColor(COLORS["text_dim"]))
    app.setPalette(palette)
    app.setStyleSheet(QSS)

_OVERLAY_QSS = f"""
/* --- capture overlay (PrintScreen) --- */
QWidget#CaptureOverlay {{ background: transparent; }}
QFrame#CaptureCard {{ background: rgba(13, 21, 38, 244); border: 1px solid #2E4470;
                      border-radius: 16px; }}
#OverlayTitle {{ font-size: 13px; font-weight: 700; color: #E8EDF7; letter-spacing: 0.4px; }}
#OverlayBadge {{ color: #FFFFFF; background: {COLORS['accent_soft']};
                 border: 1px solid {COLORS['accent']}; border-radius: 10px;
                 padding: 2px 10px; font-size: 12px; font-weight: 600; }}
#OverlayHint {{ color: #A4B4D8; font-size: 12px; }}
QPushButton#ModeButton {{ background: {COLORS['card']}; border: 2px solid {COLORS['border']};
                          border-radius: 12px; color: {COLORS['text']};
                          font-size: 14px; padding: 10px 6px; }}
QPushButton#ModeButton:hover {{ border-color: {COLORS['accent']}; background: {COLORS['card_alt']}; }}
QPushButton#ModeButton[current="true"] {{ border: 2px solid {COLORS['accent']};
                                          background: {COLORS['accent_soft']}; color: #FFFFFF; }}
"""

QSS = QSS + _OVERLAY_QSS
