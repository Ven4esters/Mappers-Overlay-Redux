from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .styles import OVERLAY_STYLESHEET
from .tabs import CalibrationTab, JoinTab, MovementTab


class ToolsDialog(QDialog):
    """
    Отдельное окно с «продвинутыми» инструментами — чтобы главный оверлей оставался компактным.
    Вкладки те же, что и раньше: движение, стыковка, калибровка.
    """

    settings_requested = Signal()

    def __init__(self, settings, advance_reference: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Инструменты — LSP Mapper Assist")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, settings.always_on_top)
        self.setModal(False)
        self.setMinimumWidth(560)
        self.setStyleSheet(OVERLAY_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.tabs = QTabWidget()
        self.movement_tab = MovementTab(settings)
        self.join_tab = JoinTab(settings, advance_reference)
        self.calibration_tab = CalibrationTab(settings)
        self.tabs.addTab(self.movement_tab, "Движение")
        self.tabs.addTab(self.join_tab, "Стыковка и Линейка")
        self.tabs.addTab(self.calibration_tab, "Калибровка")
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        self.btn_settings = QPushButton("Настройки…")
        self.btn_settings.setToolTip("Прозрачность, точность чисел, тайминги, горячие клавиши")
        self.btn_settings.clicked.connect(lambda: self.settings_requested.emit())
        buttons.addButton(self.btn_settings, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(buttons)

    # Удобные короткие имена для главного окна
    @property
    def movement(self) -> MovementTab:
        return self.movement_tab

    @property
    def calibration(self) -> CalibrationTab:
        return self.calibration_tab

    def show_tab(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        # Прячем окно вместо уничтожения, чтобы не терять состояние инструментов
        event.ignore()
        self.hide()
