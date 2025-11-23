from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Iterable

import pydirectinput


@dataclass
class InputTimings:
    min_delay: float = 0.01
    max_delay: float = 0.05
    mouse_step_ms: float = 10.0


class InputHandler:
    """Low-level-friendly input wrapper with human-like timing."""

    def __init__(self, timings: InputTimings | None = None) -> None:
        self.timings = timings or InputTimings()
        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False

    def _human_delay(self, base: float | None = None) -> None:
        delay = base if base is not None else random.uniform(self.timings.min_delay, self.timings.max_delay)
        time.sleep(delay)

    def _bezier_path(self, start: tuple[int, int], end: tuple[int, int], steps: int) -> Iterable[tuple[int, int]]:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        ctrl1 = (
            start[0] + dx * 0.3 + random.randint(-25, 25),
            start[1] + dy * 0.1 + random.randint(-25, 25),
        )
        ctrl2 = (
            start[0] + dx * 0.6 + random.randint(-25, 25),
            start[1] + dy * 0.9 + random.randint(-25, 25),
        )

        for i in range(1, steps + 1):
            t = i / steps
            x = int(
                (1 - t) ** 3 * start[0]
                + 3 * (1 - t) ** 2 * t * ctrl1[0]
                + 3 * (1 - t) * t**2 * ctrl2[0]
                + t**3 * end[0]
            )
            y = int(
                (1 - t) ** 3 * start[1]
                + 3 * (1 - t) ** 2 * t * ctrl1[1]
                + 3 * (1 - t) * t**2 * ctrl2[1]
                + t**3 * end[1]
            )
            yield x, y

    def move_mouse(self, x: int, y: int, duration: float = 0.35) -> None:
        start = pydirectinput.position()
        steps = max(int(duration * 1000 / self.timings.mouse_step_ms), 8)
        for point in self._bezier_path(start, (x, y), steps):
            pydirectinput.moveTo(point[0], point[1])
            self._human_delay(self.timings.mouse_step_ms / 1000.0)

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.move_mouse(x, y)
        self._human_delay()
        pydirectinput.click(button=button)
        self._human_delay()

    def tap_key(self, key: str) -> None:
        pydirectinput.press(key)
        self._human_delay()

    def key_down(self, key: str) -> None:
        pydirectinput.keyDown(key)
        self._human_delay()

    def key_up(self, key: str) -> None:
        pydirectinput.keyUp(key)
        self._human_delay()

    def type_text(self, text: str, interval_range: tuple[float, float] = (0.02, 0.08)) -> None:
        for char in text:
            pydirectinput.press(char)
            self._human_delay(random.uniform(*interval_range))
