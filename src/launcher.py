from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
OWNER = "your-org"
REPO = "legacy-rpa"
VERSION_FILE = Path(__file__).resolve().parent / "version.txt"
BIN_DIR = Path(__file__).resolve().parent / "bin"
CORE_EXECUTABLE = BIN_DIR / "Core.exe"


@dataclass
class ReleaseAsset:
    name: str
    download_url: str


@dataclass
class ReleaseInfo:
    version: str
    assets: list[ReleaseAsset]

    @classmethod
    def from_api(cls, payload: dict) -> "ReleaseInfo":
        version = str(payload.get("tag_name", "0.0.0")).lstrip("v")
        assets = [
            ReleaseAsset(asset["name"], asset["browser_download_url"])
            for asset in payload.get("assets", [])
        ]
        return cls(version=version, assets=assets)

    def select_core_asset(self) -> Optional[ReleaseAsset]:
        # Prefer explicit Core.exe, otherwise accept a zip package.
        for name in ("Core.exe", "core.exe", "core.zip", "Core.zip"):
            for asset in self.assets:
                if asset.name.lower() == name.lower():
                    return asset
        for asset in self.assets:
            if asset.name.lower().endswith("core.exe") or asset.name.lower().endswith("core.zip"):
                return asset
        return None


class VersionManager:
    def __init__(self, version_file: Path) -> None:
        self.version_file = version_file

    def read(self) -> str:
        if self.version_file.exists():
            return self.version_file.read_text().strip()
        return "0.0.0"

    def write(self, version: str) -> None:
        self.version_file.write_text(version)

    @staticmethod
    def newer_than(remote: str, local: str) -> bool:
        def to_tuple(value: str) -> tuple[int, int, int]:
            parts = value.split(".")
            padded = (parts + ["0", "0", "0"])[:3]
            return tuple(int(p) if p.isdigit() else 0 for p in padded)  # type: ignore[return-value]

        return to_tuple(remote) > to_tuple(local)


def fetch_latest_release(owner: str, repo: str) -> ReleaseInfo:
    response = requests.get(GITHUB_API.format(owner=owner, repo=repo), timeout=10)
    response.raise_for_status()
    return ReleaseInfo.from_api(response.json())


def download_asset(asset: ReleaseAsset, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / asset.name

    with requests.get(asset.download_url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with destination.open("wb") as target:
            shutil.copyfileobj(response.raw, target)

    return destination


def install_core(archive_or_exe: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    if archive_or_exe.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as extract_dir:
            shutil.unpack_archive(str(archive_or_exe), extract_dir)
            extracted_core = None
            for candidate in Path(extract_dir).rglob("Core.exe"):
                extracted_core = candidate
                break
            if not extracted_core:
                raise FileNotFoundError("Downloaded package does not contain Core.exe")
            shutil.copy2(extracted_core, destination)
    else:
        shutil.copy2(archive_or_exe, destination)


def launch_core(executable: Path) -> None:
    if not executable.exists():
        raise FileNotFoundError(f"Core executable not found at {executable}")
    subprocess.Popen([str(executable)], cwd=executable.parent)


def notify(message: str) -> None:
    print(message)


def main() -> None:
    version_mgr = VersionManager(VERSION_FILE)
    local_version = version_mgr.read()

    try:
        release = fetch_latest_release(OWNER, REPO)
        asset = release.select_core_asset()
        should_update = VersionManager.newer_than(release.version, local_version) and asset is not None
    except Exception:
        release = None
        asset = None
        should_update = False

    if should_update and asset:
        notify("업데이트 중: 최신 코어를 다운로드합니다...")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                downloaded = download_asset(asset, Path(temp_dir))
                install_core(downloaded, CORE_EXECUTABLE)
            version_mgr.write(release.version)
            notify("업데이트 완료")
        except Exception:
            notify("업데이트에 실패하여 기존 코어를 실행합니다.")

    try:
        launch_core(CORE_EXECUTABLE)
    except FileNotFoundError:
        notify("로컬 코어를 찾을 수 없습니다. '/bin/Core.exe' 위치를 확인하세요.")


if __name__ == "__main__":
    main()
