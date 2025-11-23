from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VERSION_FILE = Path.home() / ".gersang_rpa_version"


@dataclass
class VersionInfo:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> "VersionInfo":
        major, minor, patch = (int(part) for part in raw.strip().split("."))
        return cls(major, minor, patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_newer_than(self, other: "VersionInfo") -> bool:
        return (self.major, self.minor, self.patch) > (other.major, other.minor, other.patch)


def read_local_version() -> VersionInfo | None:
    if VERSION_FILE.exists():
        return VersionInfo.parse(VERSION_FILE.read_text())
    return None


def write_local_version(version: VersionInfo) -> None:
    VERSION_FILE.write_text(str(version))
