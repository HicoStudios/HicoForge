"""
Persist pending queue between launches.

On close, the MainWindow asks the JobQueue for its pending jobs and writes
them here. On launch, it reads them back and re-enqueues. Files that no
longer exist are dropped silently.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import List

from core import config as cfgmod


FILENAME = "pending_queue.json"


def store_path() -> Path:
    return cfgmod.config_dir() / FILENAME


def save_pending(items: List[dict]) -> bool:
    path = store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "items": items}, f, indent=2)
        tmp.replace(path)
        return True
    except Exception:
        return False


def load_pending() -> List[dict]:
    path = store_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    # Only keep entries with at least source_path
    return [d for d in items if isinstance(d, dict) and d.get("source_path")]


def clear_pending() -> None:
    path = store_path()
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
