from __future__ import annotations

import sys
from typing import Iterable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config import RuntimeConfig, ensure_directories
from core.input_control import InputController
from core.vision import TemplateMatcher


class MainWindow(QMainWindow):
    def __init__(self, config: RuntimeConfig, matcher: TemplateMatcher, controller: InputController) -> None:
        super().__init__()
        self.config = config
        self.matcher = matcher
        self.controller = controller

        self.setWindowTitle("Legacy DirectX RPA")
        self.status_label = QLabel("대기 중")
        self.result_list = QListWidget()

        self.capture_button = QPushButton("지금 캡처")
        self.capture_button.clicked.connect(self.capture_once)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.capture_button)
        layout.addWidget(self.result_list)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.capture_once)
        self.timer.start(500)

    def capture_once(self) -> None:
        matches = self.matcher.capture_and_locate()
        self._render_results(matches)
        self.status_label.setText(f"감지된 템플릿: {len(matches)}개")

    def _render_results(self, matches: Iterable[tuple[str, tuple[int, int], float]]) -> None:
        self.result_list.clear()
        for name, (x, y), score in matches:
            item = QListWidgetItem(f"{name}: ({x},{y}) -> {score:.2f}")
            if score >= self.config.vision.threshold:
                item.setForeground(QColor("green"))
            self.result_list.addItem(item)


def bootstrap() -> None:
    config = RuntimeConfig()
    ensure_directories(config)

    matcher = TemplateMatcher(config)
    controller = InputController(config.inputs)
    controller.enable_low_level_compatibility()

    app = QApplication(sys.argv)
    window = MainWindow(config, matcher, controller)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    bootstrap()
