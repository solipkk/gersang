from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, List

import mss
import numpy as np
from PySide6 import QtCore

from core import window_manager
from core.safety_lock import SafetyLock

ActionCallback = Callable[[window_manager.WindowInfo, int], None]


@dataclass
class SchedulerSettings:
    switch_delay: float = 0.2
    action_delay: float = 0.5


class SchedulerThread(QtCore.QThread):
    window_started = QtCore.Signal(int, str)
    window_removed = QtCore.Signal(int, str)
    render_timeout = QtCore.Signal(int, str)
    log = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(
        self,
        windows: Iterable[window_manager.WindowInfo],
        settings: SchedulerSettings,
        action_callback: ActionCallback | None = None,
        safety_lock: SafetyLock | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.windows: List[window_manager.WindowInfo] = window_manager.filter_windows(list(windows))
        self.settings = settings
        self.action_callback = action_callback
        self.safety_lock = safety_lock
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:  # pragma: no cover - long-running thread
        if not self.windows:
            self.finished.emit()
            return

        with mss.mss() as sct:
            while self._running and self.windows:
                for idx, info in list(enumerate(self.windows)):
                    if not self._running:
                        break

                    if not window_manager.is_window_valid(info.hwnd):
                        self._remove_window(idx, info)
                        continue

                    self.window_started.emit(idx, info.title)
                    if not window_manager.bring_to_front(info.hwnd):
                        self.log.emit(f"Failed to focus window: {info.title}")
                        continue

                    time.sleep(max(0.0, self.settings.switch_delay))
                    frame = self._wait_for_render(sct, info, idx)
                    if frame is None:
                        self.render_timeout.emit(idx, info.title)
                        continue

                    if self.safety_lock and self.safety_lock.evaluate(frame, info.title, idx):
                        self.log.emit("Safety lock engaged; stopping scheduler.")
                        self._running = False
                        break

                    if self.action_callback:
                        try:
                            self.action_callback(info, idx)
                        except Exception as exc:  # pragma: no cover - defensive
                            self.log.emit(f"Action error on {info.title}: {exc}")

                    time.sleep(max(0.0, self.settings.action_delay))

                    if self.safety_lock:
                        remote_cmd = self.safety_lock.poll_remote()
                        if remote_cmd == "stop":
                            self.log.emit("Remote stop received; aborting scheduler")
                            self._running = False
                            break
                        if remote_cmd == "resume":
                            self.log.emit("Remote resume acknowledged; continuing")

        self.finished.emit()

    def _remove_window(self, idx: int, info: window_manager.WindowInfo) -> None:
        try:
            self.windows.pop(idx)
        except IndexError:
            return
        self.window_removed.emit(idx, info.title)

    def _wait_for_render(
        self, sct: mss.base.MSSBase, info: window_manager.WindowInfo, idx: int
    ) -> np.ndarray | None:
        deadline = time.time() + 1.0
        while self._running and time.time() < deadline:
            rect = window_manager.get_window_rect(info.hwnd)
            if rect is None:
                self._remove_window(idx, info)
                return None

            left, top, right, bottom = rect
            width = max(1, right - left)
            height = max(1, bottom - top)
            monitor = {"left": left, "top": top, "width": width, "height": height}

            try:
                shot = np.array(sct.grab(monitor))
            except Exception:
                time.sleep(0.05)
                continue

            mean_pixel = shot[..., :3].mean()
            if mean_pixel > 5:
                return shot
            time.sleep(0.05)

        return None
