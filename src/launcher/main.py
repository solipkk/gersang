from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from launcher.updater import Updater, write_update_result

DEFAULT_OWNER = "your-org"
DEFAULT_REPO = "legacy-rpa"


class Launcher:
    def __init__(self, owner: str, repo: str, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.updater = Updater(owner, repo, base_dir)

    def run(self, launch_core: bool = True, log_path: Path | None = None) -> None:
        release = self.updater.check_and_update()
        if log_path:
            write_update_result(log_path, release)

        if launch_core:
            self._start_core()

    def _start_core(self) -> None:
        executable = self.base_dir / "core" / "core.exe"
        script = self.base_dir / "core" / "main.py"

        if executable.exists():
            subprocess.Popen([str(executable)], cwd=executable.parent)
        elif script.exists():
            subprocess.Popen(["python", str(script)], cwd=script.parent)
        else:
            raise FileNotFoundError("No core entrypoint found in the installed package")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launcher for the RPA core module")
    parser.add_argument("--owner", default=DEFAULT_OWNER, help="GitHub owner name")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repository name")
    parser.add_argument("--no-launch", action="store_true", help="Only update, do not start core")
    parser.add_argument("--log", type=Path, default=None, help="Path to write update metadata")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="Installation directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    launcher = Launcher(args.owner, args.repo, args.base_dir)
    launcher.run(launch_core=not args.no_launch, log_path=args.log)


if __name__ == "__main__":
    main()
