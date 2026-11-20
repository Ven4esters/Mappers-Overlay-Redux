from __future__ import annotations

OVERLAY_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #11161d;
    color: #e6edf3;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}

QWidget {
    color: #e6edf3;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}

QGroupBox {
    background-color: #171e27;
    border: 1px solid #283444;
    border-radius: 7px;
    margin-top: 8px;
    padding: 8px 7px 7px 7px;
    font-weight: 600;
    color: #9fb3c8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 9px;
    padding: 0 5px;
    color: #8ab4f8;
}

QTabWidget::pane {
    border: 1px solid #283444;
    border-radius: 7px;
    background-color: #141a22;
    top: -1px;
}

QTabBar::tab {
    background-color: #18202a;
    color: #93a4b8;
    border: 1px solid #283444;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 10px;
    margin-right: 3px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background-color: #1f2b3a;
    color: #ffffff;
    border-color: #3b82f6;
}

QTabBar::tab:hover:!selected {
    background-color: #1c2633;
    color: #d0dceb;
}

QPushButton {
    background-color: #212b38;
    color: #e6edf3;
    border: 1px solid #324154;
    border-radius: 5px;
    padding: 4px 8px;
    font-weight: 600;
    min-height: 22px;
}

QPushButton:hover {
    background-color: #2b394a;
    border-color: #4c6482;
}

QPushButton:pressed {
    background-color: #19222d;
}

QPushButton:disabled {
    background-color: #161c24;
    color: #596778;
    border-color: #222b36;
}

QPushButton:checked {
    background-color: #1d4ed8;
    border-color: #60a5fa;
    color: #ffffff;
}

QPushButton#btnCapture {
    background-color: #1e3a5f;
    border-color: #3b82f6;
    color: #eaf2ff;
}
QPushButton#btnCapture:hover {
    background-color: #254b7c;
}

QPushButton#btnSaveCommit {
    background-color: #14532d;
    border-color: #22c55e;
    color: #ecfdf5;
}
QPushButton#btnSaveCommit:hover {
    background-color: #166534;
}

QPushButton#btnWarn {
    background-color: #5c3b09;
    border-color: #f59e0b;
    color: #fef3c7;
}
QPushButton#btnWarn:hover {
    background-color: #784d0c;
}

QPushButton#btnMovePrimary {
    background-color: #233142;
    border-color: #3d5673;
    font-size: 12px;
    min-height: 26px;
}
QPushButton#btnMovePrimary:hover {
    background-color: #2e4259;
    border-color: #60a5fa;
}

QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {
    background-color: #0e1319;
    color: #f0f6fc;
    border: 1px solid #2d3a4b;
    border-radius: 4px;
    padding: 3px 5px;
    selection-background-color: #2563eb;
}

QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus {
    border-color: #3b82f6;
}

QCheckBox {
    spacing: 6px;
    color: #cbd5e1;
}

QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 1px solid #425469;
    background-color: #0e1319;
}

QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #60a5fa;
}

QLabel#statusBanner {
    background-color: #16202c;
    border: 1px solid #273649;
    border-radius: 5px;
    padding: 5px 8px;
    color: #cbd5e1;
}

QLabel#calibActiveBanner {
    background-color: #422006;
    border: 1px solid #f59e0b;
    border-radius: 6px;
    padding: 6px 8px;
    color: #fde68a;
    font-weight: 600;
}
"""

# --- Компактный режим: маленькие кнопки и крестовина ---
COMPACT_OVERLAY_ADDITIONS = """
QPushButton#btnSmall {
    font-size: 13px;
    padding: 2px 7px;
    min-height: 22px;
    background-color: #1b2430;
    border: 1px solid #2b3746;
    border-radius: 5px;
}
QPushButton#btnSmall:hover { background-color: #24303f; }
QPushButton#btnSmall:checked {
    background-color: #1d3a5f;
    border-color: #3b82f6;
    color: #dbeafe;
}

QPushButton#btnTools {
    font-size: 12px;
    padding: 2px 8px;
    background-color: #1b2430;
    border: 1px solid #2b3746;
    border-radius: 5px;
    color: #9fb3c8;
}
QPushButton#btnTools:hover { background-color: #24303f; color: #dbeafe; }

QPushButton#btnDpad {
    font-size: 15px;
    font-weight: 600;
    padding: 1px;
    min-height: 28px;
    background-color: #1e2836;
    border: 1px solid #2f3d4f;
    border-radius: 5px;
}
QPushButton#btnDpad:hover { background-color: #2a3a4d; border-color: #3b82f6; }
QPushButton#btnDpad:pressed { background-color: #3b82f6; color: #0b1220; }

QDoubleSpinBox#coordSpin::up-button,
QDoubleSpinBox#coordSpin::down-button {
    width: 0px;
    border: none;
    background: transparent;
}
QDoubleSpinBox#coordSpin {
    padding: 2px 6px;
    min-height: 22px;
    font-size: 12px;
}

QLabel#dpadCenter {
    background-color: #141b24;
    border: 1px dashed #2f3d4f;
    border-radius: 5px;
    color: #7dd3fc;
    font-size: 11px;
    font-weight: 600;
}
"""


OVERLAY_STYLESHEET = OVERLAY_STYLESHEET + COMPACT_OVERLAY_ADDITIONS
