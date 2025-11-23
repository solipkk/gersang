from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def clean() -> None:
    for folder in (Path("build"), Path("dist")):
        if folder.exists():
            shutil.rmtree(folder)


def build() -> None:
    clean()
    output = Path("dist")
    output.mkdir(exist_ok=True)
    cmd = [
        "python",
        "-m",
        "nuitka",
        "--onefile",
        "--standalone",
        "--windows-disable-console",
        "--enable-plugin=pyside6",
        "--windows-icon=icon.ico",
        "--lto=no",
        "--include-data-dir=templates=templates",
        "--include-data-dir=profiles=profiles",
        "--include-data-file=config.json=config.json",
        "--output-dir",
        str(output),
        "--output-filename",
        "GersangAuto_v1.0.exe",
        "src/main.py",
    ]
    subprocess.check_call(cmd)


if __name__ == "__main__":
    build()
