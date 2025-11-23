from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import psutil
from PySide6 import QtCore


@dataclass
class WatchdogConfig:
    process_name: str = ""
    process_path: str = ""
    hang_timeout_minutes: int = 5


class WatchdogThread(QtCore.QThread):
    """Background watchdog that ensures a target process stays healthy."""

    status = QtCore.Signal(str)
    restarted = QtCore.Signal(str)
    killed = QtCore.Signal(str)

    def __init__(self, config: WatchdogConfig, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._stop_event = Event()
        self._last_activity = time.monotonic()

    # Activity & control -------------------------------------------------
    def stop(self) -> None:
        self._stop_event.set()

    def report_activity(self) -> None:
        self._last_activity = time.monotonic()

    # Process helpers ----------------------------------------------------
    def is_process_running(self) -> bool:
        target = self.config.process_name.lower()
        if not target:
            return False
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name")
            if name and name.lower() == target:
                return True
        return False

    def restart_process(self) -> None:
        if not self.config.process_path:
            return
        exe_path = Path(self.config.process_path)
        if not exe_path.exists():
            self.status.emit(f"Watchdog: executable not found at {exe_path}")
            return
        try:
            subprocess.Popen([str(exe_path)])
            self.restarted.emit(str(exe_path))
            self.report_activity()
        except Exception as exc:  # pragma: no cover - runtime guard
            self.status.emit(f"Watchdog failed to restart process: {exc}")

    def _kill_processes(self) -> None:
        target = self.config.process_name.lower()
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name")
            if name and name.lower() == target:
                try:
                    proc.kill()
                    self.killed.emit(name)
                except psutil.NoSuchProcess:
                    continue
                except Exception:
                    continue

    def _check_hang(self) -> None:
        timeout_sec = max(1, self.config.hang_timeout_minutes) * 60
        inactive_for = time.monotonic() - self._last_activity
        if inactive_for < timeout_sec:
            return
        self.status.emit("Watchdog: detected hang, restarting process")
        self._kill_processes()
        self.restart_process()

    # Thread loop -------------------------------------------------------
    def run(self) -> None:  # pragma: no cover - thread loop
        while not self._stop_event.is_set():
            if self.config.process_name:
                if not self.is_process_running():
                    self.status.emit("Watchdog: process missing, attempting restart")
                    self.restart_process()
                else:
                    self._check_hang()
            self._stop_event.wait(10.0)
