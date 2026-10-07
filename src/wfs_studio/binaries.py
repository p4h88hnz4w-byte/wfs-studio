"""Download and check the official wfs-tools release binaries."""

from __future__ import annotations

import hashlib
import os
import platform
import stat
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

RELEASE = "v1.2.3"
DOWNLOAD_BASE = f"https://github.com/koolkdev/wfs-tools/releases/download/{RELEASE}/"
USER_AGENT = "wfs-studio/0.1"


@dataclass(frozen=True)
class Asset:
    filename: str
    sha256: str


ASSETS = {
    "macos-arm64": Asset(
        "wfs-tools-v1.2.3-macos-arm64.zip",
        "7c7be53f1bc5dd1713003303eee8dc858c0449121c7ac3a3e4eed6a3400f9d8e",
    ),
    "macos-x64": Asset(
        "wfs-tools-v1.2.3-macos-x64.zip",
        "95b74de917624c0c2c9153ead3dcdeafd8230bdb4badf4ea25e2ab0b96e6507f",
    ),
    "linux-x86-64": Asset(
        "wfs-tools-v1.2.3-linux-x86-64.zip",
        "948491695977f6dafb643db22f215a43fda2cabd5626c5a25eca9f3927b59415",
    ),
    "windows-x64": Asset(
        "wfs-tools-v1.2.3-windows-x64.zip",
        "cec9a6bdd3870194cbd77282c8bb6cda70048c085c41ec4a5851cf55b2b01411",
    ),
}


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    system_name = (system if system is not None else platform.system()).lower()
    machine_name = (machine if machine is not None else platform.machine()).lower()
    if system_name == "darwin" and machine_name in {"arm64", "aarch64"}:
        return "macos-arm64"
    if system_name == "darwin" and machine_name in {"x86_64", "amd64"}:
        return "macos-x64"
    if system_name == "linux" and machine_name in {"x86_64", "amd64"}:
        return "linux-x86-64"
    if system_name == "windows" and machine_name in {"x86_64", "amd64"}:
        return "windows-x64"
    known = ", ".join(sorted(ASSETS))
    raise RuntimeError(
        f"No official wfs-tools build for {system_name} {machine_name}. Known builds: {known}."
    )


def executable_name(system: str | None = None) -> str:
    system_name = (system if system is not None else platform.system()).lower()
    if system_name == "windows":
        return "wfs-extract.exe"
    return "wfs-extract"


def repo_root() -> Path:
    override = os.environ.get("WFS_STUDIO_HOME")
    if override:
        return Path(override).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "wfs_studio").is_dir():
            return parent
    return here.parents[2]


def vendor_dir(root: Path, key: str | None = None) -> Path:
    return root / "vendor" / "wfs-tools" / RELEASE / (key or platform_key())


def installed_binary(root: Path, key: str | None = None, system: str | None = None) -> Path | None:
    path = vendor_dir(root, key) / executable_name(system)
    if path.is_file():
        return path
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = info.filename
            parts = Path(name).parts
            if not name or name.endswith("/"):
                continue
            if name.startswith("/") or ".." in parts:
                raise RuntimeError(f"Unsafe path in wfs-tools archive: {name}")
            target = dest / name
            if not target.resolve().is_relative_to(dest.resolve()):
                raise RuntimeError(f"Unsafe path in wfs-tools archive: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                output.write(source.read())
            mode = info.external_attr >> 16
            if mode & stat.S_IXUSR:
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            elif target.name.startswith("wfs-"):
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_binary(root: Path, timeout: float = 120) -> Path:
    """Return the local wfs-extract path, downloading the official zip if needed."""
    key = platform_key()
    system = platform.system()
    existing = installed_binary(root, key, system)
    if existing is not None:
        return existing
    asset = ASSETS[key]
    download_dir = root / "cache" / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    archive = download_dir / asset.filename
    url = DOWNLOAD_BASE + asset.filename
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        archive.write_bytes(response.read())
    digest = sha256_file(archive)
    if digest != asset.sha256:
        archive.unlink(missing_ok=True)
        raise RuntimeError(
            f"Checksum mismatch for {asset.filename}. Expected {asset.sha256}, got {digest}."
        )
    destination = vendor_dir(root, key)
    safe_extract(archive, destination)
    binary = destination / executable_name(system)
    if not binary.is_file():
        raise RuntimeError(f"wfs-extract was not in the archive at {binary}.")
    return binary


def main() -> None:
    path = ensure_binary(repo_root())
    print(path)


if __name__ == "__main__":
    main()
