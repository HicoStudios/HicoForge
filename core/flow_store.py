"""
core/flow_store.py
------------------
Persistence layer for user-saved Flows in HicoForge v1.1.0.

Flows are stored as a list of serialized dicts under config["flows"] using
the existing cfgmod (core.config) load/save API.  The store is intentionally
simple — no database, no migration logic.

Public API
----------
list_flows()           -> List[Flow]
get_flow(flow_id)      -> Optional[Flow]
save_flow(flow)        -> None          (upserts by flow.id)
delete_flow(flow_id)   -> None
export_flow(flow_id, path)  -> None     (writes JSON file)
import_flow(path)           -> Flow     (reads JSON, assigns new id, saves)
new_flow_id()          -> str           (short unique id like "flow_a1b2c3")
"""

from __future__ import annotations

import json
import os
import random
import string
from pathlib import Path
from typing import Dict, List, Optional

from core import config as cfgmod
from core.flow_engine import Flow, FlowStep

_FLOWS_KEY = "flows"


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def new_flow_id() -> str:
    """Generate a short unique flow ID like ``flow_a1b2c3``."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"flow_{suffix}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_raw() -> List[Dict]:
    """Load the raw list of flow dicts from config, returning [] on error."""
    try:
        cfg = cfgmod.load_config()
        return cfg.get(_FLOWS_KEY, [])
    except Exception as e:
        print(f"[flow] flow_store._load_raw error: {e}")
        return []


def _save_raw(flows_raw: List[Dict]) -> None:
    """Persist the raw list of flow dicts back to config."""
    try:
        cfg = cfgmod.load_config()
        cfg[_FLOWS_KEY] = flows_raw
        cfgmod.save_config(cfg)
    except Exception as e:
        print(f"[flow] flow_store._save_raw error: {e}")
        raise


def _deserialize_flow(d: Dict) -> Optional[Flow]:
    """Safely deserialize a dict to a Flow, returning None on error."""
    try:
        return Flow.from_dict(d)
    except Exception as e:
        print(f"[flow] Could not deserialize flow {d.get('id', '?')}: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_flows() -> List[Flow]:
    """Return all saved flows in insertion order.

    Malformed entries are skipped with a console warning.
    """
    raw = _load_raw()
    flows: List[Flow] = []
    for d in raw:
        f = _deserialize_flow(d)
        if f is not None:
            flows.append(f)
    return flows


def get_flow(flow_id: str) -> Optional[Flow]:
    """Return the Flow with the given id, or None if not found."""
    for f in list_flows():
        if f.id == flow_id:
            return f
    return None


def save_flow(flow: Flow) -> None:
    """Persist a flow, overwriting any existing entry with the same id.

    If the flow id is empty or missing a new id is assigned automatically.
    """
    if not flow.id:
        flow.id = new_flow_id()

    raw = _load_raw()

    # Replace existing entry or append
    for i, d in enumerate(raw):
        if d.get("id") == flow.id:
            raw[i] = flow.to_dict()
            _save_raw(raw)
            return

    raw.append(flow.to_dict())
    _save_raw(raw)
    print(f"[flow] Saved flow '{flow.name}' ({flow.id})")


def delete_flow(flow_id: str) -> None:
    """Remove a flow by id.  No-op if the id does not exist."""
    raw = _load_raw()
    new_raw = [d for d in raw if d.get("id") != flow_id]
    if len(new_raw) == len(raw):
        print(f"[flow] delete_flow: id '{flow_id}' not found, nothing deleted")
        return
    _save_raw(new_raw)
    print(f"[flow] Deleted flow {flow_id}")


def export_flow(flow_id: str, path: str) -> None:
    """Write a flow's JSON representation to a file for sharing.

    Parameters
    ----------
    flow_id:
        Id of the flow to export.
    path:
        Absolute path of the destination .json file.

    Raises
    ------
    KeyError:
        If flow_id is not found.
    OSError:
        If the file cannot be written.
    """
    flow = get_flow(flow_id)
    if flow is None:
        raise KeyError(f"Flow '{flow_id}' not found")

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "hicoforge_flow_version": 1,
        "flow": flow.to_dict(),
    }
    try:
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(f"[flow] Exported '{flow.name}' to {dest}")
    except OSError as e:
        print(f"[flow] export_flow error: {e}")
        raise


def import_flow(path: str) -> Flow:
    """Import a flow from a JSON file previously exported with export_flow.

    A new unique id is assigned so the imported flow never collides with an
    existing local flow.  The imported flow is automatically saved.

    Parameters
    ----------
    path:
        Absolute path to the .json file.

    Returns
    -------
    The imported and saved Flow.

    Raises
    ------
    ValueError:
        If the file is not a valid HicoForge flow export.
    OSError:
        If the file cannot be read.
    """
    src = Path(path)
    try:
        with open(src, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as e:
        print(f"[flow] import_flow read error: {e}")
        raise

    if not isinstance(payload, dict) or "flow" not in payload:
        raise ValueError(f"'{src.name}' is not a valid HicoForge flow export")

    try:
        flow = Flow.from_dict(payload["flow"])
    except Exception as e:
        raise ValueError(f"Could not parse flow data: {e}") from e

    # Assign a fresh id to avoid collision
    flow.id = new_flow_id()
    save_flow(flow)
    print(f"[flow] Imported flow '{flow.name}' as {flow.id}")
    return flow


def rename_flow(flow_id: str, new_name: str) -> None:
    """Convenience helper: change a flow's name in-place."""
    flow = get_flow(flow_id)
    if flow is None:
        print(f"[flow] rename_flow: id '{flow_id}' not found")
        return
    flow.name = new_name
    save_flow(flow)


def duplicate_flow(flow_id: str, new_name: Optional[str] = None) -> Optional[Flow]:
    """Create a copy of an existing flow with a new id.

    Returns the new Flow, or None if the source flow was not found.
    """
    original = get_flow(flow_id)
    if original is None:
        print(f"[flow] duplicate_flow: id '{flow_id}' not found")
        return None

    import copy
    clone_dict = copy.deepcopy(original.to_dict())
    clone_dict["id"] = new_flow_id()
    clone_dict["name"] = new_name or (original.name + " (copy)")
    clone = Flow.from_dict(clone_dict)
    save_flow(clone)
    return clone
