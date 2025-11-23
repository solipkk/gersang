from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, List

import requests


class TelegramBot:
    """Lightweight Telegram bot helper using Bot API via requests."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        timeout: float = 5.0,
        poll_interval: float = 5.0,
    ) -> None:
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._last_poll = 0.0
        self._offset = 0

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def send_message(self, text: str) -> None:
        if not self.enabled:
            return
        payload = {"chat_id": self.chat_id, "text": text}
        try:
            requests.post(self._api_url("sendMessage"), json=payload, timeout=self.timeout)
        except Exception:
            return

    def send_photo(self, caption: str, image_path: str | Path) -> None:
        if not self.enabled:
            return
        path = Path(image_path)
        if not path.exists():
            return
        files = {"photo": (path.name, path.open("rb"))}
        data = {"chat_id": self.chat_id, "caption": caption}
        try:
            requests.post(self._api_url("sendPhoto"), files=files, data=data, timeout=self.timeout)
        except Exception:
            return

    def poll_commands(self) -> Iterable[str]:
        if not self.enabled:
            return []
        now = time.monotonic()
        if now - self._last_poll < self.poll_interval:
            return []
        self._last_poll = now
        try:
            response = requests.get(
                self._api_url("getUpdates"),
                params={"timeout": int(self.timeout), "offset": self._offset},
                timeout=self.timeout + 2,
            )
            data = response.json()
        except Exception:
            return []

        commands: List[str] = []
        for update in data.get("result", []):
            self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            text = (message.get("text") or "").strip()
            if text in {"/status", "/resume", "/stop"}:
                commands.append(text)
        return commands
