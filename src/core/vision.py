from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np
from mss import mss


@dataclass
class TemplateMatchResult:
    template_name: str
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]
    confidence: float
    scale: float

    @property
    def center(self) -> tuple[int, int]:
        x1, y1 = self.top_left
        x2, y2 = self.bottom_right
        return ((x1 + x2) // 2, (y1 + y2) // 2)


class TemplateMatcher:
    """Multi-scale template matcher using OpenCV.

    Designed for legacy DirectX applications where resolution may change.
    """

    def __init__(
        self,
        template_dir: str | Path,
        threshold: float = 0.82,
        scales: Sequence[float] | None = None,
        match_method: int = cv2.TM_CCOEFF_NORMED,
        capture_region: dict[str, int] | None = None,
    ) -> None:
        self.template_dir = Path(template_dir)
        self.threshold = threshold
        self.scales: Sequence[float] = scales or (1.0, 0.95, 0.9, 0.85, 0.8, 0.75)
        self.match_method = match_method
        self.capture_region = capture_region
        self._sct = mss()

    def _iter_templates(self) -> Iterable[tuple[str, np.ndarray]]:
        for template_path in self.template_dir.glob("*.png"):
            template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
            if template is None:
                continue
            yield template_path.stem, template

    def capture_frame(self) -> np.ndarray:
        raw = self._sct.grab(self.capture_region) if self.capture_region else self._sct.grab(self._sct.monitors[0])
        frame = np.array(raw)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def _match_template(self, frame: np.ndarray, template: np.ndarray) -> TemplateMatchResult | None:
        best_score = -1.0
        best_loc: tuple[int, int] = (0, 0)
        best_scale = 1.0
        h_frame, w_frame = frame.shape[:2]

        for scale in self.scales:
            resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            h_t, w_t = resized.shape[:2]
            if h_t > h_frame or w_t > w_frame:
                continue
            result = cv2.matchTemplate(frame, resized, self.match_method)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            score = max_val if self.match_method in (cv2.TM_CCOEFF, cv2.TM_CCOEFF_NORMED) else min_val
            if score > best_score:
                best_score = score
                best_loc = max_loc if self.match_method in (cv2.TM_CCOEFF, cv2.TM_CCOEFF_NORMED) else min_loc
                best_scale = scale

        if best_score < self.threshold:
            return None

        top_left = best_loc
        bottom_right = (
            int(best_loc[0] + template.shape[1] * best_scale),
            int(best_loc[1] + template.shape[0] * best_scale),
        )
        return TemplateMatchResult("", top_left, bottom_right, float(best_score), best_scale)

    def locate(self) -> list[TemplateMatchResult]:
        frame = self.capture_frame()
        matches: list[TemplateMatchResult] = []
        for name, template in self._iter_templates():
            match = self._match_template(frame, template)
            if match:
                matches.append(
                    TemplateMatchResult(
                        template_name=name,
                        top_left=match.top_left,
                        bottom_right=match.bottom_right,
                        confidence=match.confidence,
                        scale=match.scale,
                    )
                )
        return matches

    def locate_best(self) -> TemplateMatchResult | None:
        matches = self.locate()
        if not matches:
            return None
        return max(matches, key=lambda item: item.confidence)
