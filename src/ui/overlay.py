from __future__ import annotations

import time
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets


class OverlayWidget(QtWidgets.QWidget):
    """Transparent HUD overlay showing runtime status without blocking clicks."""

    def __init__(self, position: str = "top_right", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.position = position
        self.start_time = time.monotonic()
        self.last_log = ""
        self.current_state = "Idle"

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | QtCore.Qt.BypassWindowManagerHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        self.label = QtWidgets.QLabel()
        self.label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.label.setStyleSheet(
            """
            QLabel {
                color: white;
                font-size: 14px;
                font-weight: 600;
            }
            """
        )

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setColor(QtGui.QColor(0, 0, 0, 180))
        shadow.setOffset(1, 1)
        self.label.setGraphicsEffect(shadow)

        layout.addWidget(self.label)
        self._update_display()

    # Public API ---------------------------------------------------------
    def set_position(self, position: str) -> None:
        self.position = position
        self._reposition()

    def set_state(self, state: str) -> None:
        self.current_state = state
        self._update_display()

    def set_last_log(self, message: str) -> None:
        self.last_log = message
        self._update_display()

    def set_start_time(self, start_time: Optional[float]) -> None:
        self.start_time = start_time if start_time is not None else time.monotonic()
        self._update_display()

    # Layout helpers -----------------------------------------------------
    def showEvent(self, event: QtGui.QShowEvent) -> None:  # pragma: no cover - Qt hook
        super().showEvent(event)
        self._reposition()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # pragma: no cover - Qt hook
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self) -> None:
        screen = QtWidgets.QApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.geometry()
        margin = 16
        x = geometry.left() + margin if self.position == "top_left" else geometry.right() - self.width() - margin
        y = geometry.top() + margin
        self.move(x, y)

    # Rendering ----------------------------------------------------------
    def _update_display(self) -> None:
        uptime = time.monotonic() - self.start_time
        minutes, seconds = divmod(int(uptime), 60)
        formatted = f"State: {self.current_state}\nUptime: {minutes:02d}:{seconds:02d}\nLast: {self.last_log}".strip()
        self.label.setText(formatted)
        self.adjustSize()
        self._reposition()
