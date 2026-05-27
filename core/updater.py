"""
HicoForge auto-updater.

Checks GitHub Releases for a newer version, downloads the release zip,
verifies it, stages it next to the install, and hands off to an external
batch script that swaps the folder and restarts the app.

Public API:
    check_for_update(timeout=5) -> Optional[UpdateInfo]
    download_and_stage(info, progress_cb=None) -> Path
    launch_updater(staged_zip: Path, current_version: str) -> None
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

GITHUB_OWNER = "HicoStudios"
GITHUB_REPO = "HicoForge"
RELEASES_API_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)

# Paths
_HERE = Path(__file__).resolve().parent
INSTALL_ROOT = _HERE.parent             # D:\HicoForge
SCRIPTS_DIR = INSTALL_ROOT / "scripts"
STAGING_DIR = INSTALL_ROOT.parent / f"{INSTALL_ROOT.name}_update_staging"

# How long to wait on network calls before giving up (seconds)
HTTP_TIMEOUT = 8

# User agent — GitHub asks API consumers to identify themselves
USER_AGENT = "HicoForge-Updater/1.0"


# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UpdateInfo:
    """Metadata about an available update."""

    version: str                # e.g. "1.1.0"
    tag_name: str               # e.g. "v1.1.0"
    name: str                   # human-readable release title
    body: str                   # markdown changelog
    zip_url: str                # browser_download_url for the zip asset
    zip_size: int               # bytes
    sha256: Optional[str]       # checksum if published in the release body
    published_at: str           # ISO8601 timestamp


# ─────────────────────────────────────────────────────────────────────────────
# Version helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_version(v: str) -> tuple[int, ...]:
    """
    Parse '1.2.3', 'v1.2.3', '1.2.3-beta.4' into a sortable tuple.

    Pre-release suffixes are dropped — pre-releases are not offered as
    auto-updates by default. This is intentional: we'd rather miss a beta
    than push it to a user who didn't opt in.
    """
    v = v.strip().lstrip("vV")
    v = v.split("-")[0].split("+")[0]
    parts: list[int] = []
    for chunk in v.split("."):
        m = re.match(r"^(\d+)", chunk)
        parts.append(int(m.group(1)) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    """Return True if `remote` represents a strictly newer version than `local`."""
    try:
        return _parse_version(remote) > _parse_version(local)
    except Exception:
        return False


def _get_local_version() -> str:
    """Read version.py from the install root."""
    try:
        vfile = INSTALL_ROOT / "version.py"
        if vfile.exists():
            ns: dict = {}
            exec(vfile.read_text(encoding="utf-8"), ns)
            return str(ns.get("__version__", "0.0.0"))
    except Exception:
        pass
    return "0.0.0"


# ─────────────────────────────────────────────────────────────────────────────
# Network — GitHub API
# ─────────────────────────────────────────────────────────────────────────────

def _http_get_json(url: str, timeout: int = HTTP_TIMEOUT) -> Optional[dict]:
    """GET a URL and parse JSON. Returns None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None
    except Exception:
        return None


def _extract_sha256_from_body(body: str) -> Optional[str]:
    """
    Look for a SHA256 hash embedded in the release body.

    Convention: include a line like
        SHA256: 1f4a92...
    in your release notes. The updater will verify the download against it
    if found. If no hash is published, the download is still trusted on
    the basis of HTTPS to GitHub.
    """
    if not body:
        return None
    m = re.search(r"sha256[:\s]+([0-9a-fA-F]{64})", body, re.IGNORECASE)
    return m.group(1).lower() if m else None


def check_for_update(timeout: int = HTTP_TIMEOUT) -> Optional[UpdateInfo]:
    """
    Hit the GitHub Releases API and return UpdateInfo if a newer version
    is available, else None.

    Silent — never raises. Returns None for any network/parse error or
    when no update is available.
    """
    data = _http_get_json(RELEASES_API_URL, timeout=timeout)
    if not data:
        return None

    if data.get("draft") or data.get("prerelease"):
        return None  # ignore drafts and pre-releases

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None
    remote_version = tag.lstrip("vV")
    if not is_newer(remote_version, _get_local_version()):
        return None

    # Find the .zip asset
    assets = data.get("assets") or []
    zip_asset = None
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(".zip"):
            zip_asset = a
            break
    if not zip_asset:
        return None

    body = data.get("body") or ""

    return UpdateInfo(
        version=remote_version,
        tag_name=tag,
        name=str(data.get("name") or tag),
        body=body,
        zip_url=str(zip_asset.get("browser_download_url") or ""),
        zip_size=int(zip_asset.get("size") or 0),
        sha256=_extract_sha256_from_body(body),
        published_at=str(data.get("published_at") or ""),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Download + stage
# ─────────────────────────────────────────────────────────────────────────────

def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for block in iter(lambda: fp.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def download_and_stage(
    info: UpdateInfo,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """
    Download the release zip into the staging directory.

    Parameters
    ----------
    info : UpdateInfo
        From check_for_update().
    progress_cb : optional callable
        Called with (bytes_downloaded, bytes_total). May be called many
        times per second — the UI is responsible for throttling.

    Returns
    -------
    Path
        The downloaded zip on disk.

    Raises
    ------
    RuntimeError
        On download failure or checksum mismatch.
    """
    if not info.zip_url:
        raise RuntimeError("No download URL in update info.")

    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    # Clean any stale staging contents first
    for old in STAGING_DIR.glob("HicoForge-*.zip"):
        try:
            old.unlink()
        except Exception:
            pass

    out_path = STAGING_DIR / f"HicoForge-{info.version}.zip"

    req = urllib.request.Request(info.zip_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT * 4) as resp:
            total = int(resp.getheader("Content-Length") or info.zip_size or 0)
            downloaded = 0
            with out_path.open("wb") as fp:
                while True:
                    chunk = resp.read(1 << 16)  # 64KB chunks
                    if not chunk:
                        break
                    fp.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except Exception:
                            pass
    except Exception as exc:
        raise RuntimeError(f"Download failed: {exc}") from exc

    # Verify checksum if published
    if info.sha256:
        actual = _sha256_file(out_path)
        if actual.lower() != info.sha256.lower():
            try:
                out_path.unlink()
            except Exception:
                pass
            raise RuntimeError(
                f"Checksum mismatch: expected {info.sha256[:12]}…, "
                f"got {actual[:12]}…"
            )

    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Hand-off to external updater script
# ─────────────────────────────────────────────────────────────────────────────

def launch_updater(staged_zip: Path, current_version: str) -> None:
    """
    Spawn the external updater batch script in a detached process and
    exit the current Python process.

    The batch script does the destructive work — folder swap, restart —
    so it has to be external (we can't replace files we are running from).
    """
    updater_bat = SCRIPTS_DIR / "updater.bat"
    if not updater_bat.exists():
        raise FileNotFoundError(f"Updater script missing: {updater_bat}")

    # Pass args: staged zip path, install root, current version (for backup name)
    args = [
        str(updater_bat),
        str(staged_zip),
        str(INSTALL_ROOT),
        current_version,
    ]

    # Detach the subprocess so it survives this process exiting.
    # On Windows: CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP

    subprocess.Popen(
        args,
        cwd=str(INSTALL_ROOT),
        creationflags=creationflags,
        close_fds=True,
        shell=False,
    )

    # Give the .bat a moment to start before we exit
    time.sleep(0.4)


# ─────────────────────────────────────────────────────────────────────────────
# Background polling helper for the UI
# ─────────────────────────────────────────────────────────────────────────────

def check_async(callback: Callable[[Optional[UpdateInfo]], None]) -> None:
    """
    Run check_for_update() on a daemon thread and deliver the result to
    `callback` on that thread. The UI is responsible for marshalling back
    to the main thread (e.g. via a Qt signal).
    """
    def _worker() -> None:
        try:
            info = check_for_update()
        except Exception:
            info = None
        try:
            callback(info)
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True, name="UpdateChecker")
    t.start()


# ─────────────────────────────────────────────────────────────────────────────
# Convenience for the Settings tab — what version are we on?
# ─────────────────────────────────────────────────────────────────────────────

def current_version() -> str:
    return _get_local_version()
