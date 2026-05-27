"""
Job history \u2014 persistent.

Two views:

  - last(slot)      : the most recent successful (source, output) pair for
                      that tile slot (used by the click-tile-to-compare flow).
                      Kept in memory only; stale on close.
  - all_records()   : the full append-only history across all sessions.
                      Stored as JSON-lines in config_dir()/history.jsonl so
                      the History panel can show every job ever run.

Persistence is best-effort: a failed write doesn't break processing.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, List

from core import config as cfgmod


HISTORY_FILENAME = "history.jsonl"
HISTORY_MAX_LINES = 5000  # trim very long files on read


@dataclass
class JobRecord:
    source: Path
    output: Path
    tool_id: str

    # Persisted-only fields (filled in on disk; the live record only needs the
    # three above for the compare-dialog hand-off)
    timestamp: float = 0.0   # seconds since epoch
    success: bool = True
    error: str = ""


def _history_path() -> Path:
    return cfgmod.config_dir() / HISTORY_FILENAME


class JobHistory:
    def __init__(self):
        self._last: Dict[int, JobRecord] = {}
        self._path = _history_path()

    # ---- Live "last record per slot" ----
    def record(self, slot: int, source: str, output: str, tool_id: str,
               success: bool = True, error: str = ""):
        rec = JobRecord(
            source=Path(source), output=Path(output), tool_id=tool_id,
            timestamp=time.time(), success=success, error=error,
        )
        if success:
            self._last[slot] = rec
        # Always persist (failures and successes alike) to the on-disk log
        self._append_to_disk(rec)

    def last(self, slot: int) -> Optional[JobRecord]:
        rec = self._last.get(slot)
        if rec and rec.source.exists() and rec.output.exists():
            return rec
        if rec:
            self._last.pop(slot, None)
        return None

    def clear(self, slot: int):
        self._last.pop(slot, None)

    # ---- Persistent log ----
    def _append_to_disk(self, rec: JobRecord):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "source": str(rec.source),
                    "output": str(rec.output),
                    "tool_id": rec.tool_id,
                    "timestamp": rec.timestamp,
                    "success": rec.success,
                    "error": rec.error or "",
                }) + "\n")
        except Exception:
            # Persistence is best-effort; never raise from here.
            pass

    def all_records(self) -> List[JobRecord]:
        """Return every record in the on-disk history, most-recent last.

        Caps at HISTORY_MAX_LINES to keep the dialog snappy on huge logs.
        """
        path = self._path
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return []
        # Trim head if huge
        if len(lines) > HISTORY_MAX_LINES:
            lines = lines[-HISTORY_MAX_LINES:]
        out: List[JobRecord] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(JobRecord(
                    source=Path(d.get("source", "")),
                    output=Path(d.get("output", "")),
                    tool_id=d.get("tool_id", ""),
                    timestamp=float(d.get("timestamp", 0.0)),
                    success=bool(d.get("success", True)),
                    error=str(d.get("error", "") or ""),
                ))
            except Exception:
                continue
        return out

    def clear_all(self):
        """Wipe the persistent history (the in-memory 'last' is unaffected)."""
        try:
            if self._path.exists():
                self._path.unlink()
        except Exception:
            pass
