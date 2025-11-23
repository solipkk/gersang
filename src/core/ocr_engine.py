from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import easyocr
import numpy as np
from mss import mss


@dataclass
class OCRConfig:
    languages: Sequence[str] = ("en",)
    gpu: bool | None = None
    detail: int = 0


class OCREngine:
    """OCR helper that keeps the EasyOCR model warm."""

    def __init__(self, config: OCRConfig | None = None) -> None:
        self.config = config or OCRConfig()
        self.reader = self._create_reader()

    def _create_reader(self) -> easyocr.Reader:
        gpu_flag = self.config.gpu
        # Fallback to CPU if GPU initialization fails or is unavailable.
        try:
            return easyocr.Reader(list(self.config.languages), gpu=gpu_flag, verbose=False)
        except Exception:
            return easyocr.Reader(list(self.config.languages), gpu=False, verbose=False)

    def _capture_region(self, region: tuple[int, int, int, int]) -> np.ndarray:
        x, y, w, h = region
        with mss() as sct:
            raw = sct.grab({"left": x, "top": y, "width": w, "height": h})
        return np.array(raw)

    def _sanitize_text(self, fragments: Iterable[str]) -> str:
        return " ".join(fragment.strip() for fragment in fragments if fragment.strip())

    def read_text(self, region: tuple[int, int, int, int]) -> str:
        """Read text from a region defined as (x, y, w, h)."""
        image = self._capture_region(region)
        results = self.reader.readtext(image, detail=self.config.detail)
        if not results:
            return ""
        if self.config.detail:
            fragments = [text for _, text, _ in results]  # type: ignore[misc]
        else:
            fragments = results  # type: ignore[assignment]
        return self._sanitize_text(fragments)

    def read_number(self, region: tuple[int, int, int, int]) -> float | int | None:
        """Extract numeric value from OCR output with simple correction."""
        raw_text = self.read_text(region)
        if not raw_text:
            return None

        corrections = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5"})
        cleaned = raw_text.translate(corrections)

        allowed_chars = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "-"}
        numeric_text = "".join(ch for ch in cleaned if ch in allowed_chars)
        if numeric_text.count(".") > 1:
            numeric_text = numeric_text.replace(".", "", numeric_text.count(".") - 1)

        if not numeric_text.strip("-."):
            return None

        try:
            number = float(numeric_text)
        except ValueError:
            return None

        if number.is_integer():
            return int(number)
        return number
