"""
User config persistence.

Stores slot assignments, presets, and global settings in
%APPDATA%\\HicoForge\\config.json on Windows
(or ~/.config/HicoForge/config.json on Linux/macOS).
"""

import json
import os
from pathlib import Path
from typing import Any


APP_NAME = "HicoForge"


def config_dir() -> Path:
    """Platform-appropriate config directory."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        d = Path(base) / APP_NAME
    else:
        d = Path.home() / ".config" / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


DEFAULTS: dict[str, Any] = {
    "version": 1,
    # Where the user's spandrel-compatible models live
    "models_folder": "",  # set on first run; default value injected at runtime
    # Last-used grid size (1/2/4/6/8/12 or -1 for All)
    "last_grid_size": 4,
    # The currently loaded slot assignments. List of {slot, tool_id}.
    # Example: [{"slot": 0, "tool_id": "ultrasharp_v2"}, ...]
    "slot_assignments": [],
    # Saved presets: {name: {"grid": int, "slots": [...]}, ...}
    "presets": {},
    "active_preset": "",
    # Global app settings (used by later chunks)
    "output_strategy": "next_to_source",  # or "central_folder"
    "central_output_folder": "",
    "recursive_folders": True,
    "auto_unload_minutes": 10,
    "max_concurrent_jobs": 1,
    "theme": "dark",
    # Per-slot setting overrides: {"0": {"target_format": "jpg", "jpg_quality": 90}, ...}
    # Keys are slot index strings (JSON-safe). Empty by default.
    "tile_settings": {},
}


def default_models_folder() -> str:
    """Best-guess default for the user's ComfyUI models folder."""
    if os.name == "nt":
        # Try a couple of common spots; first existing wins
        candidates = [
            Path.home() / "Documents" / "ComfyUI" / "models" / "upscale_models",
            Path.home() / "ComfyUI" / "models" / "upscale_models",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        # Fall back to the user's Documents path even if it doesn't exist yet
        return str(Path.home() / "Documents" / "ComfyUI" / "models" / "upscale_models")
    else:
        return str(Path.home() / "ComfyUI" / "models" / "upscale_models")


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        cfg = dict(DEFAULTS)
        cfg["models_folder"] = default_models_folder()
        save_config(cfg)
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        cfg = dict(DEFAULTS)
        cfg["models_folder"] = default_models_folder()
        save_config(cfg)
        return cfg
    # Fill in any missing defaults (forward-compat when we add keys later)
    changed = False
    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    if not cfg.get("models_folder"):
        cfg["models_folder"] = default_models_folder()
        changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    path = config_path()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    tmp.replace(path)


# -------- Slot helpers --------

def get_slot_assignments(cfg: dict) -> dict[int, str]:
    """Return {slot_index: tool_id} from the config."""
    out = {}
    for entry in cfg.get("slot_assignments", []):
        try:
            out[int(entry["slot"])] = str(entry["tool_id"])
        except (KeyError, ValueError, TypeError):
            continue
    return out


def set_slot_assignment(cfg: dict, slot: int, tool_id: str | None) -> None:
    """Assign (or clear, if tool_id is None) a slot."""
    arr = [e for e in cfg.get("slot_assignments", []) if int(e.get("slot", -1)) != slot]
    if tool_id:
        arr.append({"slot": slot, "tool_id": tool_id})
    arr.sort(key=lambda e: int(e["slot"]))
    cfg["slot_assignments"] = arr


def clear_all_slots(cfg: dict) -> None:
    cfg["slot_assignments"] = []
