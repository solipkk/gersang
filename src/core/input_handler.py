from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Tuple

import pydirectinput


@dataclass
class InputTimings:
    min_delay: float = 0.01
    max_delay: float = 0.05
    mouse_step_ms: float = 10.0
    click_delay_mean: float = 0.085
    click_delay_std: float = 0.03
    move_duration_mean: float = 0.35
    move_duration_std: float = 0.12
    overshoot_chance: float = 0.35
    overshoot_px: int = 22
    jitter_px: int = 3


class InputHandler:
    """Low-level-friendly input wrapper with human-like timing."""

    def __init__(
        self,
        timings: InputTimings | None = None,
        dry_run: bool = False,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.timings = timings or InputTimings()
        self.dry_run = dry_run
        self.blocked = False
        self.logger = logger
        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False

    def set_dry_run(self, enabled: bool) -> None:
        self.dry_run = enabled

    def set_blocked(self, blocked: bool) -> None:
        self.blocked = blocked

    def _log(self, message: str) -> None:
        if self.logger:
            self.logger(message)

    def _gaussian_delay(self, mean: float, std: float, minimum: float = 0.0) -> float:
        delay = max(minimum, random.gauss(mean, std))
        return delay

    def _human_delay(self, base: float | None = None) -> None:
        if base is not None:
            delay = base
        else:
            delay = random.uniform(self.timings.min_delay, self.timings.max_delay)
        time.sleep(delay)

    def _should_block(self) -> bool:
        if self.blocked:
            self._log("[Safety] Input blocked; ignoring request.")
            return True
        return False

    def get_random_point(self, x: int, y: int, w: int, h: int) -> tuple[int, int]:
        cx = x + w / 2
        cy = y + h / 2
        std_x = max(1.0, w / 6)
        std_y = max(1.0, h / 6)
        rx = int(random.gauss(cx, std_x))
        ry = int(random.gauss(cy, std_y))
        rx = max(x, min(x + w - 1, rx))
        ry = max(y, min(y + h - 1, ry))
        return rx, ry

    def _bezier_path(
        self, start: tuple[int, int], end: tuple[int, int], steps: int, jitter: int = 2
    ) -> Iterable[tuple[int, int]]:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        ctrl1 = (
            start[0] + dx * 0.3 + random.randint(-25, 25),
            start[1] + dy * 0.15 + random.randint(-25, 25),
        )
        ctrl2 = (
            start[0] + dx * 0.65 + random.randint(-25, 25),
            start[1] + dy * 0.85 + random.randint(-25, 25),
        )

        for i in range(1, steps + 1):
            t = i / steps
            ease = 0.5 - 0.5 * math.cos(math.pi * t)
            x = int(
                (1 - ease) ** 3 * start[0]
                + 3 * (1 - ease) ** 2 * ease * ctrl1[0]
                + 3 * (1 - ease) * ease**2 * ctrl2[0]
                + ease**3 * end[0]
            )
            y = int(
                (1 - ease) ** 3 * start[1]
                + 3 * (1 - ease) ** 2 * ease * ctrl1[1]
                + 3 * (1 - ease) * ease**2 * ctrl2[1]
                + ease**3 * end[1]
            )
            x += random.randint(-jitter, jitter)
            y += random.randint(-jitter, jitter)
            yield x, y

    def _sample_duration(self, base_duration: float | None = None) -> float:
        mean = base_duration if base_duration is not None else self.timings.move_duration_mean
        duration = max(0.05, random.gauss(mean, self.timings.move_duration_std))
        return duration

    def move_mouse(self, x: int, y: int, duration: float | None = None) -> None:
        if self._should_block():
            return
        start = pydirectinput.position()
        end = (x, y)
        overshoot_points: List[Tuple[int, int]] = []
        if random.random() < self.timings.overshoot_chance:
            overshoot = (
                end[0] + random.randint(-self.timings.overshoot_px, self.timings.overshoot_px),
                end[1] + random.randint(-self.timings.overshoot_px, self.timings.overshoot_px),
            )
            overshoot_points.append(overshoot)

        planned_duration = self._sample_duration(duration)
        steps = max(int(planned_duration * 1000 / self.timings.mouse_step_ms), 12)
        path: list[tuple[int, int]] = []
        current_start = start
        for idx, target in enumerate([*overshoot_points, end]):
            part_steps = max(steps // (len(overshoot_points) + 1), 8)
            jitter = self.timings.jitter_px + (1 if idx == 0 and overshoot_points else 0)
            path.extend(list(self._bezier_path(current_start, target, part_steps, jitter=jitter)))
            current_start = target

        total_points = len(path)
        for i, point in enumerate(path, start=1):
            if self.dry_run:
                self._log(f"[DryRun] Move to {point}")
            else:
                pydirectinput.moveTo(point[0], point[1])
            t = i / max(total_points, 1)
            ease = 0.5 - 0.5 * math.cos(math.pi * t)
            base_delay = self.timings.mouse_step_ms / 1000.0
            variable = random.uniform(0.6, 1.4)
            micro_pause = self._gaussian_delay(base_delay * ease * variable, base_delay * 0.2, minimum=0.001)
            time.sleep(micro_pause)

    def force_move_mouse(self, x: int, y: int) -> None:
        """Bypass block to clear the cursor on freezes."""
        try:
            pydirectinput.moveTo(x, y)
        except Exception:
            return

    def click(self, x: int, y: int, button: str = "left") -> None:
        if self._should_block():
            return
        self.move_mouse(x, y)
        self._human_delay(self._gaussian_delay(self.timings.click_delay_mean, self.timings.click_delay_std, 0.01))
        if self.dry_run:
            self._log(f"[DryRun] Click {button} at ({x}, {y})")
        else:
            pydirectinput.click(button=button)
        self._human_delay(self._gaussian_delay(self.timings.click_delay_mean, self.timings.click_delay_std, 0.01))

    def click_region(self, x: int, y: int, w: int, h: int, button: str = "left") -> None:
        rx, ry = self.get_random_point(x, y, w, h)
        self.click(rx, ry, button=button)

    def tap_key(self, key: str) -> None:
        if self._should_block():
            return
        if self.dry_run:
            self._log(f"[DryRun] Tap key '{key}'")
        else:
            pydirectinput.press(key)
        self._human_delay(self._gaussian_delay(self.timings.click_delay_mean, self.timings.click_delay_std, 0.005))

    def key_down(self, key: str) -> None:
        if self._should_block():
            return
        if self.dry_run:
            self._log(f"[DryRun] Key down '{key}'")
        else:
            pydirectinput.keyDown(key)
        self._human_delay()

    def key_up(self, key: str) -> None:
        if self._should_block():
            return
        if self.dry_run:
            self._log(f"[DryRun] Key up '{key}'")
        else:
            pydirectinput.keyUp(key)
        self._human_delay()

    def type_text(self, text: str, interval_range: tuple[float, float] = (0.02, 0.08)) -> None:
        for char in text:
            if self.dry_run:
                self._log(f"[DryRun] Type '{char}'")
            else:
                pydirectinput.press(char)
            self._human_delay(random.uniform(*interval_range))
