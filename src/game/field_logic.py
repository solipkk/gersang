from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Tuple

import cv2
import mss
import numpy as np

from core.input_handler import InputHandler
from core.vision import TemplateMatcher
from game.combat_navigator import CombatNavigator, NavigatorConfig


@dataclass
class FieldConfig:
    nameplate_lower: Tuple[int, int, int] = (5, 80, 180)
    nameplate_upper: Tuple[int, int, int] = (20, 255, 255)
    shadow_lower: Tuple[int, int, int] = (0, 0, 20)
    shadow_upper: Tuple[int, int, int] = (180, 70, 80)
    click_timeout: float = 3.0
    poll_interval: float = 0.2


class FieldLogic:
    """Field targeting tuned for colored nameplates and ground rings."""

    def __init__(self, handler: InputHandler, matcher: TemplateMatcher | None = None) -> None:
        self.handler = handler
        self.matcher = matcher
        self.sct: mss.mss | None = None

    def hunt(self, navigator: CombatNavigator, nav_config: NavigatorConfig, config: FieldConfig) -> None:
        frame = self._grab_frame()
        candidates = self._find_targets(frame, config)
        if not candidates:
            return
        center = self._screen_center()
        candidates.sort(key=lambda pt: (pt[0] - center[0]) ** 2 + (pt[1] - center[1]) ** 2)

        for target in candidates:
            self.handler.move_mouse(*target)
            self.handler.click(*target, button="right")
            if self._wait_for_battle_ui(navigator, nav_config, config):
                return
        return

    # Helpers ------------------------------------------------------------
    def _grab_frame(self) -> np.ndarray:
        if self.sct is None:
            self.sct = mss.mss()
        monitor = self.sct.monitors[1]
        shot = np.array(self.sct.grab(monitor))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def _screen_center(self) -> tuple[int, int]:
        from pydirectinput import size

        width, height = size()
        return int(width / 2), int(height / 2)

    def _find_targets(self, frame: np.ndarray, config: FieldConfig) -> list[tuple[int, int]]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        nameplate_mask = cv2.inRange(hsv, config.nameplate_lower, config.nameplate_upper)
        shadow_mask = cv2.inRange(hsv, config.shadow_lower, config.shadow_upper)
        combined = cv2.bitwise_or(nameplate_mask, shadow_mask)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        points: list[tuple[int, int]] = []
        for cnt in contours:
            if cv2.contourArea(cnt) < 25:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            points.append((int(x + w / 2), int(y + h / 2)))
        return points

    def _wait_for_battle_ui(
        self, navigator: CombatNavigator, nav_config: NavigatorConfig, config: FieldConfig
    ) -> bool:
        start = time.time()
        while time.time() - start < config.click_timeout:
            if navigator.wait_for_phase_start(nav_config):
                return True
            time.sleep(config.poll_interval)
        return False
