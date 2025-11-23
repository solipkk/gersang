from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests


class Notifier:
    """Discord webhook notifier."""

    def __init__(self, webhook_url: str | None = None, timeout: float = 5.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    def _post(self, **kwargs) -> None:
        if not self.webhook_url:
            return
        try:
            response = requests.post(self.webhook_url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
        except Exception:
            # Silence network failures to avoid breaking automation loops.
            return

    def send_message(self, text: str) -> None:
        payload = {"content": text}
        self._post(json=payload)

    def send_image(self, text: str, image_path: str | Path) -> None:
        if not self.webhook_url:
            return
        path = Path(image_path)
        if not path.exists():
            return
        with path.open("rb") as handle:
            files = {"file": (path.name, handle, "application/octet-stream")}
            data = {"content": text}
            self._post(files=files, data=data)
