from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import mss
import numpy as np
import pydirectinput

from core.input_handler import InputHandler
from core.vision import TemplateMatchResult, TemplateMatcher


@dataclass
class CombatConfig:
    load_template: str | None = None
    result_templates: Sequence[str] = ("victory", "defeat", "result")
    hold_e: bool = False
    hold_e_duration: float = 0.2
    minimap_size: Tuple[int, int] = (200, 200)
    minimap_margin: int = 12


class CombatLogic:
    def __init__(self, handler: InputHandler, matcher: TemplateMatcher | None = None) -> None:
        self.handler = handler
        self.matcher = matcher
        self.sct: mss.mss | None = None

    # Battle flow ---------------------------------------------------------
    def engage_battle(self, enemy_coords: Tuple[int, int, int, int], config: CombatConfig) -> None:
        x, y, w, h = enemy_coords
        target_point = self.handler.get_random_point(x, y, w, h)
        self.handler.click(*target_point, button="right")
        self._smart_wait_for_load(config)

    def setup_phase(self) -> None:
        width, height = pydirectinput.size()
        center = (int(width / 2), int(height / 2))
        self.handler.move_mouse(*center)
        self.handler.tap_key("q")
        time.sleep(random.uniform(0.35, 0.65))
        self.handler.tap_key("w")

    def track_and_strike(self, config: CombatConfig) -> None:
        targets = self.find_enemy_clusters()
        if not targets:
            self._nudge_camera_with_minimap(config)
            targets = self.find_enemy_clusters()

        for tx, ty in targets:
            self.handler.move_mouse(tx, ty)
            if config.hold_e:
                self.handler.key_down("e")
                time.sleep(max(0.05, config.hold_e_duration))
                self.handler.key_up("e")
            else:
                self.handler.tap_key("e")

    def terminate_battle(self, config: CombatConfig, start_time: float) -> None:
        if self._detect_result(config):
            self._dismiss_result()
            return

        if time.time() - start_time > 30:
            for _ in range(4):
                self.handler.tap_key("esc")
                time.sleep(0.25)

    # Helpers -------------------------------------------------------------
    def _smart_wait_for_load(self, config: CombatConfig) -> None:
        if not self.matcher or not config.load_template:
            time.sleep(5)
            return

        end_time = time.time() + 10
        while time.time() < end_time:
            match = self._locate_template(config.load_template)
            if match:
                return
            time.sleep(0.25)

    def _locate_template(self, template_name: str) -> Optional[TemplateMatchResult]:
        if not self.matcher:
            return None
        matches = self.matcher.locate()
        for match in matches:
            if match.template_name == template_name:
                return match
        return None

    def _grab_frame(self) -> np.ndarray:
        if self.sct is None:
            self.sct = mss.mss()
        monitor = self.sct.monitors[1]
        shot = np.array(self.sct.grab(monitor))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def find_enemy_clusters(self) -> List[Tuple[int, int]]:
        frame = self._grab_frame()
        mask = self._enemy_mask(frame)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers: List[Tuple[int, int]] = []
        for cnt in contours:
            if cv2.contourArea(cnt) < 20:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            centers.append((int(x + w / 2), int(y + h / 2)))
        centers.sort(key=lambda c: c[0])
        return centers

    def _enemy_mask(self, frame: np.ndarray) -> np.ndarray:
        red_lower1 = np.array([0, 0, 120], dtype=np.uint8)
        red_upper1 = np.array([80, 80, 255], dtype=np.uint8)
        red_lower2 = np.array([0, 0, 160], dtype=np.uint8)
        red_upper2 = np.array([60, 60, 255], dtype=np.uint8)
        mask1 = cv2.inRange(frame, red_lower1, red_upper1)
        mask2 = cv2.inRange(frame, red_lower2, red_upper2)
        mask = cv2.bitwise_or(mask1, mask2)
        mask = cv2.GaussianBlur(mask, (5, 5), 0)
        _, mask = cv2.threshold(mask, 40, 255, cv2.THRESH_BINARY)
        return mask

    def _nudge_camera_with_minimap(self, config: CombatConfig) -> None:
        frame = self._grab_frame()
        h, w, _ = frame.shape
        mini_w, mini_h = self._minimap_size(config)
        margin = max(0, config.minimap_margin)
        x_start = max(0, w - mini_w - 2 * margin)
        y_start = margin
        minimap = frame[y_start : y_start + mini_h, x_start : x_start + mini_w]
        mask = self._enemy_mask(minimap)
        coords = cv2.findNonZero(mask)
        if coords is None:
            return
        mean = coords.mean(axis=0)[0]
        dx = mean[0] - mini_w / 2
        dy = mean[1] - mini_h / 2
        if abs(dx) > 5:
            key = "right" if dx > 0 else "left"
            self.handler.key_down(key)
            time.sleep(min(0.4, abs(dx) / mini_w))
            self.handler.key_up(key)
        if abs(dy) > 5:
            key = "down" if dy > 0 else "up"
            self.handler.key_down(key)
            time.sleep(min(0.4, abs(dy) / mini_h))
            self.handler.key_up(key)

    def _minimap_size(self, config: CombatConfig) -> Tuple[int, int]:
        width, height = config.minimap_size
        return max(20, int(width)), max(20, int(height))

    def _detect_result(self, config: CombatConfig) -> bool:
        if not self.matcher:
            return False
        matches = self.matcher.locate()
        return any(match.template_name in config.result_templates for match in matches)

    def _dismiss_result(self) -> None:
        self.handler.tap_key("esc")
        time.sleep(1)
        self.handler.tap_key("esc")


def engage_battle(
    handler: InputHandler,
    matcher: TemplateMatcher,
    enemy_region: Tuple[int, int, int, int],
    config: Optional[CombatConfig] = None,
) -> None:
    config = config or CombatConfig()
    logic = CombatLogic(handler, matcher)
    start_time = time.time()

    logic.engage_battle(enemy_region, config)
    logic.setup_phase()
    logic.track_and_strike(config)
    logic.terminate_battle(config, start_time)
