"""
HicoForge model downloader (Chunk 3.1).

Threaded HTTP downloader with:
  - resume support (Range requests, .part temp file)
  - progress reporting via Qt Signals
  - atomic rename on completion
  - cancellation
  - optional SHA256 verification

Use:
    job = ModelDownloadJob(url, dest_path, expected_size_mb=140, sha256=None)
    job.signals.progress.connect(lambda done, total: ...)
    job.signals.finished.connect(lambda path: ...)
    job.signals.error.connect(lambda msg: ...)
    job.start()        # returns immediately, runs in worker thread
    job.cancel()       # cooperative cancel
"""

from __future__ import annotations
import hashlib
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal


# Pretend to be a real browser. HF + GitHub releases both serve fine to anonymous,
# but some CDNs in front of them 403 the default urllib UA.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 HicoForge/0.3"
)

CHUNK_SIZE = 1024 * 256  # 256 KB chunks


class _DownloadSignals(QObject):
    # done_bytes, total_bytes, speed_bps
    progress = Signal(int, int, float)
    # final_path
    finished = Signal(str)
    # error message
    error = Signal(str)
    # cancelled (no payload)
    cancelled = Signal()


class ModelDownloadJob:
    """One download, run in a background thread."""

    def __init__(
        self,
        url: str,
        dest_path: Path,
        expected_size_mb: Optional[int] = None,
        sha256: Optional[str] = None,
    ):
        self.url = url
        self.dest_path = Path(dest_path)
        self.expected_size_mb = expected_size_mb
        self.sha256 = sha256.lower() if sha256 else None
        self.signals = _DownloadSignals()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- Public API ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="ModelDownload")
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- Worker ----
    def _run(self):
        try:
            self.dest_path.parent.mkdir(parents=True, exist_ok=True)
            part = self.dest_path.with_suffix(self.dest_path.suffix + ".part")

            # If complete file already exists, finish immediately.
            if self.dest_path.exists() and self.dest_path.stat().st_size > 0:
                self.signals.finished.emit(str(self.dest_path))
                return

            # Resume?
            resume_pos = part.stat().st_size if part.exists() else 0

            req = urllib.request.Request(self.url, headers={"User-Agent": _UA})
            if resume_pos > 0:
                req.add_header("Range", f"bytes={resume_pos}-")

            try:
                resp = urllib.request.urlopen(req, timeout=30)
            except urllib.error.HTTPError as e:
                # 416 = Range not satisfiable (already complete, server says no more)
                if e.code == 416 and part.exists():
                    part.rename(self.dest_path)
                    self.signals.finished.emit(str(self.dest_path))
                    return
                raise

            status = resp.status
            headers = resp.headers
            # total content length includes only what's left when resuming; combine.
            try:
                remaining = int(headers.get("Content-Length") or 0)
            except ValueError:
                remaining = 0
            total = resume_pos + remaining if remaining else 0

            # If server ignored Range and sent the whole file, start over.
            if resume_pos > 0 and status != 206:
                resume_pos = 0
                if part.exists():
                    part.unlink()
                total = remaining

            mode = "ab" if resume_pos > 0 else "wb"
            done = resume_pos
            last_emit = 0.0
            start_ts = time.time()
            speed = 0.0

            with open(part, mode) as f:
                while True:
                    if self._cancel.is_set():
                        try:
                            resp.close()
                        except Exception:
                            pass
                        self.signals.cancelled.emit()
                        return

                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last_emit > 0.15:
                        elapsed = max(now - start_ts, 0.001)
                        speed = (done - resume_pos) / elapsed
                        self.signals.progress.emit(done, total, speed)
                        last_emit = now

            # Final progress tick
            self.signals.progress.emit(done, total or done, speed)

            # Verify size if expected_size_mb set (rough sanity check)
            if self.expected_size_mb:
                expected_bytes = self.expected_size_mb * 1024 * 1024
                # Allow 25% tolerance — sizes are approximate
                if done < expected_bytes * 0.75:
                    part.unlink(missing_ok=True)
                    self.signals.error.emit(
                        f"Download truncated: got {done // (1024*1024)} MB, "
                        f"expected ~{self.expected_size_mb} MB"
                    )
                    return

            # SHA256 check if provided
            if self.sha256:
                h = hashlib.sha256()
                with open(part, "rb") as f:
                    for block in iter(lambda: f.read(1024 * 1024), b""):
                        if self._cancel.is_set():
                            self.signals.cancelled.emit()
                            return
                        h.update(block)
                got = h.hexdigest().lower()
                if got != self.sha256:
                    part.unlink(missing_ok=True)
                    self.signals.error.emit(
                        f"Hash mismatch.\nExpected: {self.sha256[:16]}…\nGot:      {got[:16]}…"
                    )
                    return

            # Atomic rename
            if self.dest_path.exists():
                self.dest_path.unlink()
            part.rename(self.dest_path)
            self.signals.finished.emit(str(self.dest_path))

        except urllib.error.HTTPError as e:
            self.signals.error.emit(f"HTTP {e.code}: {e.reason} — {self.url}")
        except urllib.error.URLError as e:
            self.signals.error.emit(f"Network error: {e.reason}")
        except OSError as e:
            self.signals.error.emit(f"File error: {e}")
        except Exception as e:
            self.signals.error.emit(f"Unexpected error: {e}")
