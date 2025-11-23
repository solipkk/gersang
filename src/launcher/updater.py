from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

from common.version import VersionInfo, read_local_version, write_local_version

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"


@dataclass
class AssetInfo:
    name: str
    download_url: str
    content_type: str


@dataclass
class ReleaseInfo:
    version: VersionInfo
    assets: list[AssetInfo]


class GitHubReleaseClient:
    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo

    def fetch_latest_release(self) -> ReleaseInfo:
        response = requests.get(GITHUB_API.format(owner=self.owner, repo=self.repo), timeout=15)
        response.raise_for_status()
        payload = response.json()

        tag = payload.get("tag_name", "0.0.0").lstrip("v")
        assets = [
            AssetInfo(asset["name"], asset["browser_download_url"], asset.get("content_type", ""))
            for asset in payload.get("assets", [])
        ]
        return ReleaseInfo(version=VersionInfo.parse(tag), assets=assets)


class Updater:
    def __init__(self, owner: str, repo: str, install_dir: Path) -> None:
        self.client = GitHubReleaseClient(owner, repo)
        self.install_dir = install_dir
        self.install_dir.mkdir(parents=True, exist_ok=True)

    def _select_core_asset(self, assets: Iterable[AssetInfo]) -> AssetInfo | None:
        for asset in assets:
            if asset.name.endswith("core.zip"):
                return asset
        return None

    def _download_asset(self, asset: AssetInfo, destination: Path) -> Path:
        with requests.get(asset.download_url, stream=True, timeout=30) as response:
            response.raise_for_status()
            with destination.open("wb") as archive:
                shutil.copyfileobj(response.raw, archive)
        return destination

    def _extract_core(self, archive: Path) -> None:
        extract_dir = self.install_dir / "core"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(archive), str(extract_dir))

    def check_and_update(self) -> ReleaseInfo | None:
        remote = self.client.fetch_latest_release()
        local = read_local_version()

        if local and not remote.version.is_newer_than(local):
            return None

        asset = self._select_core_asset(remote.assets)
        if not asset:
            raise RuntimeError("No core package available in the latest release")

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / asset.name
            self._download_asset(asset, archive_path)
            self._extract_core(archive_path)

        write_local_version(remote.version)
        return remote


def write_update_result(result_path: Path, release: ReleaseInfo | None) -> None:
    payload = None
    if release:
        payload = {
            "version": str(release.version),
            "assets": [asset.name for asset in release.assets],
        }
    result_path.write_text(json.dumps(payload, indent=2))
