from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import pydirectinput

from core.config import InputConfig


@dataclass
class InputController:
    config: InputConfig

    def tap_key(self, key: str) -> None:
        pydirectinput.press(key)
        time.sleep(self.config.tap_delay_ms / 1000)

    def click(self, x: int, y: int) -> None:
        pydirectinput.moveTo(x, y)
        pydirectinput.click()
        time.sleep(self.config.tap_delay_ms / 1000)

    def hold_key(self, key: str, duration_ms: int) -> None:
        pydirectinput.keyDown(key)
        time.sleep(duration_ms / 1000)
        pydirectinput.keyUp(key)

    @staticmethod
    def enable_low_level_compatibility() -> None:
        if sys.platform.startswith("win"):
            pydirectinput.PAUSE = 0
            pydirectinput.FAILSAFE = False
