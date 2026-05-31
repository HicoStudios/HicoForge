"""
Global output settings — single source of truth for Run_### folder layout.

All tile drops and flow tiles (unless overridden) use:
  <output_root>/<project_folder>/Run_###/
      originals/, step_XX_<tool>/, final/, run_manifest.json
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from core.flow_run_paths import (
    OUTPUT_MODE_CUSTOM,
    OUTPUT_MODE_HICO_PROCESSED,
    OUTPUT_MODE_IN_SOURCE,
    default_output_root,
    normalize_output_mode,
    safe_folder_name,
)

_GLOBAL_OUTPUT_KEY = "global_output"
_DEFAULT_FILENAME_PATTERN = "{source_name}__r{run_id}__{step_name}"


def default_global_output(install_root: Path) -> Dict[str, Any]:
    return {
        "output_mode": OUTPUT_MODE_HICO_PROCESSED,
        "output_root": str(default_output_root(install_root)),
        "custom_output_folder": "",
        "project_folder_name": "Default",
        "base_name_override": "",
        "filename_pattern": _DEFAULT_FILENAME_PATTERN,
    }


def _coerce_global_output(raw: Any, install_root: Path) -> Dict[str, Any]:
    base = default_global_output(install_root)
    if isinstance(raw, dict):
        base.update(raw)
    base["output_mode"] = normalize_output_mode(str(base.get("output_mode") or OUTPUT_MODE_HICO_PROCESSED))
    base["project_folder_name"] = safe_folder_name(
        str(base.get("project_folder_name") or "Default"),
        "Default",
    )
    pattern = str(base.get("filename_pattern") or "").strip()
    base["filename_pattern"] = pattern or _DEFAULT_FILENAME_PATTERN
    if not str(base.get("output_root") or "").strip():
        base["output_root"] = str(default_output_root(install_root))
    return base


def migrate_config(cfg: dict, install_root: Path) -> bool:
    """Ensure global_output exists; keep legacy TrialFlow separate. Returns True if changed."""
    changed = False
    install_root = Path(install_root)

    if _GLOBAL_OUTPUT_KEY not in cfg or not isinstance(cfg.get(_GLOBAL_OUTPUT_KEY), dict):
        cfg[_GLOBAL_OUTPUT_KEY] = default_global_output(install_root)
        changed = True

    before = deepcopy(cfg[_GLOBAL_OUTPUT_KEY])
    cfg[_GLOBAL_OUTPUT_KEY] = _coerce_global_output(cfg[_GLOBAL_OUTPUT_KEY], install_root)
    if cfg[_GLOBAL_OUTPUT_KEY] != before:
        changed = True

    if "legacy_trialflow_output" not in cfg:
        cfg["legacy_trialflow_output"] = False
        changed = True

    # Preserve old central_output_folder only as legacy debug path (do not map to output_root).
    if "central_output_folder" not in cfg:
        cfg["central_output_folder"] = ""
        changed = True

    return changed


def get_global_output(cfg: dict, install_root: Optional[Path] = None) -> Dict[str, Any]:
    if install_root is None:
        install_root = Path(__file__).resolve().parent.parent
    migrate_config(cfg, install_root)
    return deepcopy(_coerce_global_output(cfg.get(_GLOBAL_OUTPUT_KEY) or {}, install_root))


def save_global_output(cfg: dict, global_output: Dict[str, Any], install_root: Optional[Path] = None) -> None:
    if install_root is None:
        install_root = Path(__file__).resolve().parent.parent
    cfg[_GLOBAL_OUTPUT_KEY] = _coerce_global_output(global_output, install_root)


def use_legacy_trialflow(cfg: dict) -> bool:
    return bool(cfg.get("legacy_trialflow_output", False))


def global_to_tile_cfg(
    global_output: Dict[str, Any],
    install_root: Optional[Path] = None,
    *,
    tile_id: str = "",
    display_name: str = "",
) -> Dict[str, Any]:
    """Convert global output dict to flow_tile_config-compatible dict."""
    go = _coerce_global_output(global_output, install_root or Path(__file__).resolve().parent.parent)
    return {
        "tile_id": tile_id,
        "display_name": display_name or go.get("project_folder_name", "Default"),
        "output_mode": go["output_mode"],
        "output_root": go["output_root"],
        "custom_output_folder": go.get("custom_output_folder", ""),
        "flow_folder_name": go["project_folder_name"],
        "base_name_override": go.get("base_name_override", ""),
        "filename_pattern": go["filename_pattern"],
    }


def effective_flow_tile_cfg(
    cfg: dict,
    tile_cfg: Dict[str, Any],
    install_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Merge global settings with optional per-flow-tile overrides."""
    if install_root is None:
        install_root = Path(__file__).resolve().parent.parent
    base = global_to_tile_cfg(
        get_global_output(cfg, install_root),
        install_root,
        tile_id=str(tile_cfg.get("tile_id") or ""),
        display_name=str(tile_cfg.get("display_name") or ""),
    )
    if not bool(tile_cfg.get("override_global_output")):
        return base

    merged = dict(base)
    if str(tile_cfg.get("flow_folder_name") or "").strip():
        merged["flow_folder_name"] = safe_folder_name(tile_cfg["flow_folder_name"], "Flow")
    if str(tile_cfg.get("base_name_override") or "").strip():
        merged["base_name_override"] = str(tile_cfg.get("base_name_override") or "")
    if str(tile_cfg.get("filename_pattern") or "").strip():
        merged["filename_pattern"] = str(tile_cfg.get("filename_pattern") or "")
    if bool(tile_cfg.get("override_output_mode")):
        merged["output_mode"] = normalize_output_mode(str(tile_cfg.get("output_mode") or merged["output_mode"]))
        if str(tile_cfg.get("output_root") or "").strip():
            merged["output_root"] = str(tile_cfg.get("output_root") or "")
        if str(tile_cfg.get("custom_output_folder") or "").strip():
            merged["custom_output_folder"] = str(tile_cfg.get("custom_output_folder") or "")
    return merged


def global_output_summary(cfg: dict, install_root: Optional[Path] = None) -> str:
    go = get_global_output(cfg, install_root)
    mode = go["output_mode"]
    if mode == OUTPUT_MODE_IN_SOURCE:
        return "(in source folder — flat filenames)"
    if mode == OUTPUT_MODE_CUSTOM:
        root = go.get("custom_output_folder") or "(custom folder)"
    else:
        root = go.get("output_root") or "(output root)"
    project = go.get("project_folder_name") or "Default"
    return f"{root}\\{project}\\Run_###"
