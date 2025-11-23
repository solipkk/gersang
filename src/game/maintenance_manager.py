from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import cv2
import mss
import numpy as np

from core.input_handler import InputHandler
from core.vision import TemplateMatcher


@dataclass
class MaintenanceConfig:
    """Configuration for post-combat recovery workflows."""

    profile_roi: Tuple[int, int, int, int] = (24, 240, 180, 520)
    fullness_roi: Tuple[int, int, int, int] = (820, 1000, 280, 60)
    inventory_roi: Tuple[int, int, int, int] = (480, 260, 960, 560)
    revive_item_names: Sequence[str] = ("삼계탕", "반계탕", "samgyetang", "revive")
    food_item_names: Sequence[str] = ("음식", "식사", "food", "meal")
    saturation_dead_threshold: int = 35
    value_dead_threshold: int = 65
    min_dead_area: int = 220
    fullness_color_lower: Tuple[int, int, int] = (5, 80, 120)
    fullness_color_upper: Tuple[int, int, int] = (25, 255, 255)
    fullness_ratio_threshold: float = 0.25
    inventory_wait: float = 1.5
    poll_interval: float = 0.2


class MaintenanceManager:
    """Post-battle maintenance for revives and feeding."""

    def __init__(
        self,
        handler: InputHandler,
        matcher: TemplateMatcher | None = None,
        logger: callable | None = None,
    ) -> None:
        self.handler = handler
        self.matcher = matcher
        self.logger = logger
        self._sct: mss.mss | None = None

    # Public API ---------------------------------------------------------
    def run(self, config: MaintenanceConfig) -> bool:
        frame = self._grab_frame()
        dead_profiles = self._detect_dead_profiles(frame, config)
        hungry = self._needs_feeding(frame, config)

        if not dead_profiles and not hungry:
            self._log("Maintenance: no revive/feeding needed.")
            return False

        self._log("Maintenance: opening inventory for recovery.")
        self.handler.tap_key("i")
        self._wait_for_inventory(config)

        updated_frame = self._grab_frame()
        if dead_profiles:
            self._revive_profiles(updated_frame, dead_profiles, config)
        if hungry:
            self._feed_party(updated_frame, config)

        self.handler.tap_key("esc")
        self._log("Maintenance complete; closing inventory.")
        return True

    # Detection ----------------------------------------------------------
    def _detect_dead_profiles(
        self, frame: np.ndarray, config: MaintenanceConfig
    ) -> List[tuple[int, int]]:
        x, y, w, h = config.profile_roi
        roi = frame[y : y + h, x : x + w]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        mask = cv2.bitwise_and(
            cv2.threshold(sat, config.saturation_dead_threshold, 255, cv2.THRESH_BINARY_INV)[1],
            cv2.threshold(val, config.value_dead_threshold, 255, cv2.THRESH_BINARY_INV)[1],
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers: list[tuple[int, int]] = []
        for cnt in contours:
            if cv2.contourArea(cnt) < config.min_dead_area:
                continue
            cx, cy, cw, ch = cv2.boundingRect(cnt)
            centers.append((x + int(cx + cw / 2), y + int(cy + ch / 2)))
        if centers:
            self._log(f"Detected {len(centers)} fallen mercenary slots for revival.")
        return centers

    def _needs_feeding(self, frame: np.ndarray, config: MaintenanceConfig) -> bool:
        x, y, w, h = config.fullness_roi
        roi = frame[y : y + h, x : x + w]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, config.fullness_color_lower, config.fullness_color_upper)
        ratio = float(cv2.countNonZero(mask)) / max(1, mask.size)
        if ratio < config.fullness_ratio_threshold:
            self._log(f"Fullness low (ratio={ratio:.3f}); feeding required.")
            return True
        return False

    # Actions ------------------------------------------------------------
    def _revive_profiles(
        self, frame: np.ndarray, targets: Iterable[tuple[int, int]], config: MaintenanceConfig
    ) -> None:
        item = self._locate_item(frame, config.revive_item_names, config)
        if not item:
            self._log("No revive item found in inventory; skipping revival.")
            return
        self.handler.click(*item)
        for idx, point in enumerate(targets, start=1):
            self.handler.click(*point)
            self._log(f"Applied revive item to profile #{idx} at {point}.")
            time.sleep(0.15)

    def _feed_party(self, frame: np.ndarray, config: MaintenanceConfig) -> None:
        item = self._locate_item(frame, config.food_item_names, config)
        if not item:
            self._log("No food item found in inventory; skipping feeding.")
            return
        self.handler.click(*item)
        self.handler.click(*item, button="right")
        self._log("Feeding triggered via inventory item.")

    # Matching -----------------------------------------------------------
    def _locate_item(
        self, frame: np.ndarray, names: Sequence[str], config: MaintenanceConfig
    ) -> tuple[int, int] | None:
        if self.matcher is None:
            return None

        x, y, w, h = config.inventory_roi
        search_area = frame[y : y + h, x : x + w]
        best_point: tuple[int, int] | None = None
        best_score = -1.0
        threshold = getattr(self.matcher, "threshold", 0.82)
        scales = getattr(self.matcher, "scales", (1.0,))

        for name in names:
            template_path = Path(self.matcher.template_dir) / f"{name}.png"
            if not template_path.exists():
                continue
            template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
            if template is None:
                continue
            match = self._match_template(search_area, template, scales)
            if match and match[2] > threshold and match[2] > best_score:
                best_score = match[2]
                best_point = (x + match[0], y + match[1])

        if best_point:
            self._log(f"Located inventory item with score {best_score:.3f} at {best_point}.")
        return best_point

    def _match_template(
        self, frame: np.ndarray, template: np.ndarray, scales: Sequence[float]
    ) -> tuple[int, int, float] | None:
        h_frame, w_frame = frame.shape[:2]
        best_score = -1.0
        best_loc = (0, 0)

        for scale in scales:
            resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            h_t, w_t = resized.shape[:2]
            if h_t > h_frame or w_t > w_frame:
                continue
            result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = float(max_val)
                best_loc = max_loc
        if best_score < 0:
            return None
        cx = int(best_loc[0] + template.shape[1] / 2)
        cy = int(best_loc[1] + template.shape[0] / 2)
        return cx, cy, best_score

    # Helpers ------------------------------------------------------------
    def _grab_frame(self) -> np.ndarray:
        if self._sct is None:
            self._sct = mss.mss()
        monitor = self._sct.monitors[1]
        shot = np.array(self._sct.grab(monitor))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def _wait_for_inventory(self, config: MaintenanceConfig) -> None:
        end = time.time() + config.inventory_wait
        while time.time() < end:
            frame = self._grab_frame()
            x, y, w, h = config.inventory_roi
            roi = frame[y : y + h, x : x + w]
            brightness = roi.mean()
            if brightness > 20:
                return
            time.sleep(config.poll_interval)

    def _log(self, message: str) -> None:
        if self.logger:
            self.logger(message)
        elif self.handler.logger:
            self.handler.logger(message)
