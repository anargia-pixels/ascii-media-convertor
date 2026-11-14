"""Replace the running standalone binary with the latest GitHub release."""

import hashlib
import json
import os
import platform
import ssl
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from http.client import HTTPResponse
from pathlib import Path

import certifi

from ascii_media import __version__

# Release source
REPO = "anargia-pixels/ascii-media-convertor"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())  # bundled CAs

# Progress callbacks
OnStart = Callable[[int | None], None]  # receives the total size in bytes
OnChunk = Callable[[int], None]  # receives the size of each downloaded chunk


def is_standalone() -> bool:
    """Return True when this process runs from the PyInstaller binary."""
    return getattr(sys, "frozen", False)


def parse_version(version: str) -> tuple[int, ...]:
    """Turn "v1.2.3" or "1.2.3" into (1, 2, 3) for comparison."""
    return tuple(int(part) for part in version.lstrip("v").split("."))


def asset_name() -> str:
    """Return the release asset name for this OS and CPU, as CI names it.

    Raises ValueError on a platform that has no release binary.
    """
    system = platform.system()
    if system == "Windows":
        return "ascii-media-windows-x86_64.exe"  # ARM64 runs it through emulation
    os_name = {"Linux": "linux", "Darwin": "macos"}.get(system)
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}
    cpu = arch.get(platform.machine().lower())
    if os_name is None or cpu is None:
        raise ValueError(f"No release binary for {system} {platform.machine()}")
    return f"ascii-media-{os_name}-{cpu}"


def open_url(url: str) -> HTTPResponse:
    """Open a URL with the bundled CA list and a client User-Agent."""
    request = urllib.request.Request(url, headers={"User-Agent": "ascii-media"})
    return urllib.request.urlopen(request, context=SSL_CONTEXT, timeout=30)


def latest_tag() -> str:
    """Return the tag of the latest release, such as "v1.2.0"."""
    with open_url(API_URL) as response:
        return json.load(response)["tag_name"]


def is_newer(tag: str) -> bool:
    """Return True when the release tag is newer than the running version."""
    return parse_version(tag) > parse_version(__version__)


def download(tag: str, dest: Path, on_start: OnStart, on_chunk: OnChunk) -> None:
    """Download the asset for this platform and check it against SHA256SUMS.

    Raises ValueError when the checksum is missing or does not match.
    """
    name = asset_name()

    # Load: read the expected hash from the release checksum file.
    with open_url(f"{DOWNLOAD_URL}/{tag}/SHA256SUMS") as response:
        lines = response.read().decode().splitlines()
    sums = {file: digest for digest, file in (line.split() for line in lines)}
    if name not in sums:
        raise ValueError(f"Release {tag} has no checksum for {name}")

    # Fetch: stream the binary to disk and hash it on the way.
    digest = hashlib.sha256()
    with open_url(f"{DOWNLOAD_URL}/{tag}/{name}") as response, dest.open("wb") as out:
        length = response.headers.get("Content-Length")
        on_start(int(length) if length else None)
        while chunk := response.read(1 << 16):
            out.write(chunk)
            digest.update(chunk)
            on_chunk(len(chunk))
    if digest.hexdigest() != sums[name]:
        raise ValueError(f"Checksum mismatch for {name}")


def stale_path(exe: Path) -> Path:
    """Return where Windows keeps the replaced binary until the next start."""
    return exe.with_name(f"{exe.name}.old")


def remove_stale() -> None:
    """Delete the binary that a previous Windows update left behind."""
    if is_standalone():
        stale_path(Path(sys.executable)).unlink(missing_ok=True)


def fetch(tag: str, on_start: OnStart, on_chunk: OnChunk) -> Path:
    """Download the release next to the running binary and return its path.

    Uses the same directory so the later rename stays on one filesystem.
    Deletes the partial file on failure.
    """
    exe = Path(sys.executable).resolve()
    fd, name = tempfile.mkstemp(prefix=".ascii-media-", dir=exe.parent)
    os.close(fd)
    new = Path(name)
    try:
        download(tag, new, on_start, on_chunk)
        new.chmod(0o755)
    except BaseException:
        new.unlink(missing_ok=True)
        raise
    return new


def swap(new: Path) -> Path:
    """Replace the running binary with the fetched one and return its path.

    PyInstaller imports modules from the binary file, so after this returns
    the process must not import anything. On failure, the old binary stays.
    """
    exe = Path(sys.executable).resolve()
    try:
        if os.name != "nt":
            os.replace(new, exe)
            return exe

        # Windows cannot overwrite a running .exe, but it can rename it.
        old = stale_path(exe)
        old.unlink(missing_ok=True)
        exe.rename(old)
        try:
            os.replace(new, exe)
        except OSError:
            old.rename(exe)  # put the working binary back
            raise
    finally:
        new.unlink(missing_ok=True)
    return exe
