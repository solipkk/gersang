from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

import cv2
import mss
import numpy as np
import pydirectinput

from core.input_handler import InputHandler
from core.vision import TemplateMatchResult, TemplateMatcher


@dataclass
class MinimapState:
    friend_centroid: Optional[Tuple[int, int]]
    enemy_centroid: Optional[Tuple[int, int]]
    direction: Optional[Tuple[float, float]]
    raw_mask: np.ndarray


@dataclass
class NavigatorConfig:
    minimap_roi: Tuple[int, int, int, int] = (12, 12, 220, 220)
    skill_bar_roi: Tuple[int, int, int, int] = (760, 960, 400, 120)
    result_templates: tuple[str, ...] = ("victory", "defeat", "result")
    hp_pixel_threshold: int = 650
    hp_mask_blur: Tuple[int, int] = (7, 7)
    max_wait_for_ui: float = 10.0
    poll_interval: float = 0.25
    e_radius: int = 400


class CombatNavigator:
    """Minimap-guided combat navigation with camera alignment and skill sequencing."""

    def __init__(self, handler: InputHandler, matcher: TemplateMatcher | None = None) -> None:
        self.handler = handler
        self.matcher = matcher
        self.sct: mss.mss | None = None

    # Public API ---------------------------------------------------------
    def wait_for_phase_start(self, config: NavigatorConfig) -> bool:
        end_time = time.time() + config.max_wait_for_ui
        while time.time() < end_time:
            frame = self._grab_frame()
            if self._is_skill_bar_visible(frame, config):
                return True
            time.sleep(config.poll_interval)
        return False

    def analyze_minimap(self, frame: np.ndarray, config: NavigatorConfig) -> MinimapState:
        x, y, w, h = config.minimap_roi
        minimap = frame[y : y + h, x : x + w]
        red_mask, blue_mask = self._color_masks(minimap)
        red_centroid = self._centroid(red_mask)
        blue_centroid = self._centroid(blue_mask)
        direction = None
        if red_centroid and blue_centroid:
            dx = float(red_centroid[0] - blue_centroid[0])
            dy = float(red_centroid[1] - blue_centroid[1])
            magnitude = (dx**2 + dy**2) ** 0.5
            if magnitude > 1e-3:
                direction = (dx / magnitude, dy / magnitude)
        combined_mask = cv2.bitwise_or(red_mask, blue_mask)
        return MinimapState(friend_centroid=blue_centroid, enemy_centroid=red_centroid, direction=direction, raw_mask=combined_mask)

    def center_camera_on_enemies(self, analysis: MinimapState, config: NavigatorConfig) -> None:
        if not analysis.direction:
            return
        dx, dy = analysis.direction
        horizontal = "right" if dx > 0 else "left"
        vertical = "down" if dy > 0 else "up"
        intensity = max(abs(dx), abs(dy))
        pulse = max(0.08, min(0.45, intensity * 0.35))
        self._tap_with_duration(horizontal, pulse)
        self._tap_with_duration(vertical, pulse * 0.7)

    def view_has_enemies(self, frame: np.ndarray, config: NavigatorConfig) -> bool:
        mask = self._hp_bar_mask(frame, blur=config.hp_mask_blur)
        pixels = int(cv2.countNonZero(mask))
        return pixels >= config.hp_pixel_threshold

    def execute_skill_sequence(self, config: NavigatorConfig) -> None:
        width, height = pydirectinput.size()
        center = (int(width / 2), int(height / 2))
        self.handler.move_mouse(*center)
        self.handler.tap_key("q")
        time.sleep(0.1)
        self.handler.tap_key("w")
        time.sleep(0.1)
        self._cast_precision_e(center, config)

    def detect_result(self, config: NavigatorConfig) -> bool:
        if not self.matcher:
            return False
        matches = self.matcher.locate()
        return any(self._is_result_match(match, config) for match in matches)

    # Core flow ----------------------------------------------------------
    def navigate_and_attack(self, config: NavigatorConfig, timeout: float = 30.0) -> None:
        if not self.wait_for_phase_start(config):
            return

        start = time.time()
        while time.time() - start < timeout:
            frame = self._grab_frame()
            analysis = self.analyze_minimap(frame, config)
            self.center_camera_on_enemies(analysis, config)

            if self.view_has_enemies(frame, config):
                self.execute_skill_sequence(config)

            if self.detect_result(config):
                break
            time.sleep(config.poll_interval)

    # Helpers ------------------------------------------------------------
    def _grab_frame(self) -> np.ndarray:
        if self.sct is None:
            self.sct = mss.mss()
        monitor = self.sct.monitors[1]
        shot = np.array(self.sct.grab(monitor))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def _is_skill_bar_visible(self, frame: np.ndarray, config: NavigatorConfig) -> bool:
        if self.matcher:
            for match in self.matcher.locate():
                if match.template_name.lower().startswith("skill"):
                    return True
        x, y, w, h = config.skill_bar_roi
        roi = frame[y : y + h, x : x + w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 160)
        edge_strength = cv2.countNonZero(edges) / max(1, roi.shape[0] * roi.shape[1])
        brightness = float(gray.mean())
        return brightness > 55 and edge_strength > 0.02

    def _color_masks(self, minimap: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        red1 = cv2.inRange(hsv, (0, 70, 90), (10, 255, 255))
        red2 = cv2.inRange(hsv, (160, 70, 90), (180, 255, 255))
        red_mask = cv2.bitwise_or(red1, red2)
        blue_mask = cv2.inRange(hsv, (95, 80, 80), (130, 255, 255))
        red_mask = cv2.GaussianBlur(red_mask, (5, 5), 0)
        blue_mask = cv2.GaussianBlur(blue_mask, (5, 5), 0)
        return red_mask, blue_mask

    def _centroid(self, mask: np.ndarray) -> Optional[Tuple[int, int]]:
        moments = cv2.moments(mask)
        if moments["m00"] == 0:
            return None
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
        return cx, cy

    def _tap_with_duration(self, key: str, duration: float) -> None:
        self.handler.key_down(key)
        time.sleep(duration)
        self.handler.key_up(key)

    def _hp_bar_mask(self, frame: np.ndarray, blur: Tuple[int, int]) -> np.ndarray:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        red1 = cv2.inRange(hsv, (0, 50, 90), (10, 255, 255))
        red2 = cv2.inRange(hsv, (160, 50, 90), (180, 255, 255))
        mask = cv2.bitwise_or(red1, red2)
        mask = cv2.GaussianBlur(mask, blur, 0)
        _, mask = cv2.threshold(mask, 60, 255, cv2.THRESH_BINARY)
        return mask

    def _cast_precision_e(self, center: tuple[int, int], config: NavigatorConfig) -> None:
        frame = self._grab_frame()
        mask = self._hp_bar_mask(frame, blur=config.hp_mask_blur)
        y, x = np.ogrid[: mask.shape[0], : mask.shape[1]]
        dist_sq = (x - center[0]) ** 2 + (y - center[1]) ** 2
        radial_mask = dist_sq <= config.e_radius**2
        focus = cv2.bitwise_and(mask, mask, mask=radial_mask.astype(np.uint8))
        heatmap = cv2.GaussianBlur(focus, (21, 21), 0)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(heatmap)
        if max_val < 10:
            return
        targets = self._top_intensity_points(heatmap, count=3, min_distance=45)
        for tx, ty in targets:
            self.handler.move_mouse(tx, ty)
            self.handler.tap_key("e")
            time.sleep(0.1)

    def _top_intensity_points(self, heatmap: np.ndarray, count: int = 3, min_distance: int = 40) -> Iterable[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        heatmap_copy = heatmap.copy()
        for _ in range(count):
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(heatmap_copy)
            if max_val < 5:
                break
            points.append(max_loc)
            cv2.circle(heatmap_copy, max_loc, min_distance, 0, -1)
        return points

    def _is_result_match(self, match: TemplateMatchResult, config: NavigatorConfig) -> bool:
        name = match.template_name.lower()
        return any(token in name for token in config.result_templates)
