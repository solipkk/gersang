from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist" / "core"
SRC_DIR = BASE_DIR / "src"


def run(command: list[str]) -> None:
    print("Running:", " ".join(command))
    subprocess.run(command, check=True)


def build_core() -> None:
    entrypoint = SRC_DIR / "core" / "main.py"
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--windows-disable-console",
        "--enable-plugin=pyside6",
        f"--output-dir={DIST_DIR}",
        "--output-filename=Core.exe",
        str(entrypoint),
    ]
    run(command)


if __name__ == "__main__":
    build_core()
