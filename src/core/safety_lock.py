from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from core.input_handler import InputHandler
from utils.notifier import Notifier
from utils.telegram_bot import TelegramBot


@dataclass
class ThreatSignals:
    minimap_missing_secs: float = 10.0
    blackout_secs: float = 10.0
    chat_burst_ratio: float = 3.0
    popup_contrast_threshold: float = 45.0


class SafetyLock:
    """Detect suspicious overlays/GM text and freeze automation instantly."""

    def __init__(
        self,
        handler: InputHandler,
        notifier: Notifier | None = None,
        telegram_bot: TelegramBot | None = None,
        logger: Callable[[str], None] | None = None,
        signals: ThreatSignals | None = None,
    ) -> None:
        self.handler = handler
        self.notifier = notifier
        self.telegram_bot = telegram_bot
        self.logger = logger or (lambda msg: None)
        self.signals = signals or ThreatSignals()
        self.locked = False
        self.last_minimap_seen = time.monotonic()
        self.last_non_black = time.monotonic()
        self.last_chat_intensity: float | None = None

    def evaluate(self, frame: np.ndarray, window_title: str = "", client_index: int = 0) -> bool:
        now = time.monotonic()
        if frame.shape[-1] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        h, w, _ = frame.shape

        # 1) Minimap occluded or vanished
        mini_size = (max(40, int(w * 0.12)), max(40, int(h * 0.12)))
        minimap = frame[0 : mini_size[1], 0 : mini_size[0]]
        minimap_mean = float(np.mean(cv2.cvtColor(minimap, cv2.COLOR_BGR2GRAY)))
        if minimap_mean > 6:
            self.last_minimap_seen = now

        # 2) Blackout detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        overall_mean = float(np.mean(gray))
        if overall_mean > 4:
            self.last_non_black = now

        # 3) Popup / quiz contrast spike in center region
        cy, cx = h // 2, w // 2
        center = gray[max(0, cy - h // 8) : min(h, cy + h // 8), max(0, cx - w // 6) : min(w, cx + w // 6)]
        contrast = float(center.max() - center.min())

        # 4) GM chat detection on lower left region (purple/red bursts)
        chat_roi = frame[int(h * 0.7) : h, 0 : max(60, int(w * 0.2))]
        chat_mask = cv2.inRange(chat_roi, (60, 0, 60), (255, 80, 255))
        chat_intensity = float(cv2.countNonZero(chat_mask)) / max(1, chat_mask.size)
        burst = False
        if self.last_chat_intensity is not None and chat_intensity > self.last_chat_intensity * self.signals.chat_burst_ratio:
            burst = True
        self.last_chat_intensity = chat_intensity

        blackout = now - self.last_non_black > self.signals.blackout_secs
        minimap_gone = now - self.last_minimap_seen > self.signals.minimap_missing_secs
        popup = contrast > self.signals.popup_contrast_threshold and minimap_mean < 4

        if blackout or minimap_gone or popup or burst:
            reason = self._reason_text(blackout, minimap_gone, popup, burst)
            self.freeze(reason, frame, window_title, client_index)
            return True
        return False

    def freeze(self, reason: str, frame: np.ndarray | None = None, window_title: str = "", client_index: int = 0) -> None:
        if self.locked:
            return
        self.locked = True
        self.logger(f"[Safety] Threat detected on {window_title or 'client'}: {reason}")
        self.handler.force_move_mouse(0, 0)
        self.handler.set_blocked(True)
        screenshot_path: Path | None = None
        if frame is not None:
            screenshot_path = Path(tempfile.gettempdir()) / f"threat_{int(time.time())}.png"
            cv2.imwrite(str(screenshot_path), frame)
        if self.notifier:
            if screenshot_path and screenshot_path.exists():
                self.notifier.send_image(f"⚠️ Threat detected: {reason}", screenshot_path)
            else:
                self.notifier.send_message(f"⚠️ Threat detected: {reason}")
        if self.telegram_bot:
            caption = f"🚨 [Client#{client_index + 1}] {reason}"
            if screenshot_path and screenshot_path.exists():
                self.telegram_bot.send_photo(caption, screenshot_path)
            else:
                self.telegram_bot.send_message(caption)

    def unlock(self) -> None:
        if not self.locked:
            return
        self.locked = False
        self.handler.set_blocked(False)
        self.logger("[Safety] Lock released; resuming control.")

    def poll_remote(self) -> str | None:
        if not self.telegram_bot:
            return None
        for command in self.telegram_bot.poll_commands():
            if command == "/status":
                self.telegram_bot.send_message("✅ Bot is locked waiting for resume." if self.locked else "✅ Bot is idle.")
            elif command == "/resume":
                self.unlock()
                return "resume"
            elif command == "/stop":
                return "stop"
        return None

    def _reason_text(self, blackout: bool, minimap_gone: bool, popup: bool, burst: bool) -> str:
        reasons = []
        if blackout:
            reasons.append("black screen")
        if minimap_gone:
            reasons.append("minimap missing")
        if popup:
            reasons.append("popup/quiz overlay")
        if burst:
            reasons.append("suspicious chat burst")
        return ", ".join(reasons) or "unknown"
