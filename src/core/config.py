from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEMPLATE_DIR = Path("templates")
DEFAULT_CAPTURE_REGION = None  # Capture full screen by default


@dataclass
class VisionConfig:
    template_dir: Path = DEFAULT_TEMPLATE_DIR
    threshold: float = 0.85
    region = DEFAULT_CAPTURE_REGION


@dataclass
class InputConfig:
    tap_delay_ms: int = 35
    repeat_delay_ms: int = 80


@dataclass
class RuntimeConfig:
    vision: VisionConfig = VisionConfig()
    inputs: InputConfig = InputConfig()


def ensure_directories(config: RuntimeConfig) -> None:
    config.vision.template_dir.mkdir(parents=True, exist_ok=True)
