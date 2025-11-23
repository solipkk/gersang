from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

try:  # dxcam is Windows-centric; guard import for tooling environments
    import dxcam  # type: ignore
except Exception:  # pragma: no cover - optional dependency in non-Windows CI
    dxcam = None


@dataclass
class AssistConfig:
    capture_fps: int = 60
    arrow_lower: tuple[int, int, int] = (0, 100, 180)  # reddish arrow hue range
    arrow_upper: tuple[int, int, int] = (20, 255, 255)
    box_color: QtGui.QColor = QtGui.QColor(220, 20, 60, 180)
    poll_timeout: float = 15.0


class BoxOverlay(QtWidgets.QWidget):
    """Transparent overlay that draws a persistent red rectangle."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.rect: Optional[QtCore.QRect] = None
        self.color = QtGui.QColor(220, 20, 60, 180)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | QtCore.Qt.BypassWindowManagerHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

    def set_box(self, rect: Optional[QtCore.QRect], color: QtGui.QColor) -> None:
        self.rect = rect
        self.color = color
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # pragma: no cover - GUI rendering
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.rect:
            pen = QtGui.QPen(self.color)
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(self.rect)


class MinigameAssist(QtCore.QThread):
    """Track the marked character and overlay a red box without clicking."""

    status = QtCore.Signal(str)

    def __init__(self, config: AssistConfig | None = None, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self.config = config or AssistConfig()
        self.camera = dxcam.create(output_color="BGR") if dxcam else None
        self.tracker: cv2.Tracker | None = None
        self.overlay = BoxOverlay()
        self.running = False

    def stop(self) -> None:
        self.running = False
        if self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass
        self.overlay.hide()

    def run(self) -> None:  # pragma: no cover - realtime thread
        if not self.camera:
            self.status.emit("dxcam unavailable; cannot start assist")
            return
        self.running = True
        self.overlay.show()
        try:
            self.camera.start(target_fps=self.config.capture_fps)
        except Exception:
            self.status.emit("Failed to start dxcam capture")
            self.running = False
            return

        init_deadline = time.time() + self.config.poll_timeout
        while self.running:
            frame = self.camera.get_latest_frame()
            if frame is None:
                time.sleep(0.01)
                continue
            bgr = np.array(frame)
            if self.tracker is None:
                bbox = self._find_marker(bgr)
                if bbox is None:
                    if time.time() > init_deadline:
                        self.status.emit("Marker not found; giving up")
                        break
                    continue
                self.tracker = self._create_tracker()
                self.tracker.init(bgr, bbox)
                self.status.emit("Marker locked; tracking")

            ok, box = self.tracker.update(bgr) if self.tracker else (False, None)
            if not ok or box is None:
                self.status.emit("Tracking lost; re-arming")
                self.tracker = None
                init_deadline = time.time() + self.config.poll_timeout
                continue

            x, y, w, h = [int(v) for v in box]
            rect = QtCore.QRect(x, y, w, h)
            self.overlay.set_box(rect, self.config.box_color)

        self.stop()

    def _find_marker(self, frame: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(self.config.arrow_lower, dtype=np.uint8), np.array(self.config.arrow_upper, dtype=np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 20:
            return None
        return tuple(map(int, cv2.boundingRect(largest)))

    def _create_tracker(self) -> cv2.Tracker:
        if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
            return cv2.legacy.TrackerCSRT_create()
        return cv2.TrackerCSRT_create()
