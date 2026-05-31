"""
Per-tile configuration for fixed Flow tiles in All-tab mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config as cfgmod
from core.flow_engine import Flow, FlowStep
from core.flow_run_paths import (
    OUTPUT_MODE_CUSTOM,
    OUTPUT_MODE_HICO_PROCESSED,
    OUTPUT_MODE_IN_SOURCE,
    safe_folder_name,
)
from core.flow_store import get_flow, new_flow_id

_FLOW_TILE_SLOTS_KEY = "flow_tile_slots"
_DEFAULT_TILE_IDS = ("all_flow_1", "all_flow_2")
_DEFAULT_FILENAME_PATTERN = "{source_name}__r{run_id}__{step_name}"


def default_tile_config(tile_id: str, install_root: Path) -> Dict[str, Any]:
    n = tile_id.rsplit("_", 1)[-1]
    folder = f"Flow_{n}"
    return {
        "tile_id": tile_id,
        "display_name": f"Flow {n}",
        "flow_id": "",
        "steps": [],
        "override_global_output": False,
        "flow_folder_name": folder,
        "base_name_override": "",
        "filename_pattern": _DEFAULT_FILENAME_PATTERN,
    }


def _normalize_tile(tile_id: str, raw: Dict[str, Any], install_root: Path) -> Dict[str, Any]:
    base = default_tile_config(tile_id, install_root)
    if isinstance(raw, dict):
        base.update(raw)
    base["tile_id"] = tile_id
    base["override_global_output"] = bool(base.get("override_global_output"))
    if base["override_global_output"]:
        base["flow_folder_name"] = safe_folder_name(
            str(base.get("flow_folder_name") or f"Flow_{tile_id.rsplit('_', 1)[-1]}"),
            "Flow",
        )
    pattern = str(base.get("filename_pattern") or "").strip()
    if base["override_global_output"] and pattern:
        base["filename_pattern"] = pattern
    elif base["override_global_output"]:
        base["filename_pattern"] = _DEFAULT_FILENAME_PATTERN
    steps = base.get("steps")
    if not isinstance(steps, list):
        base["steps"] = []
    return base


def get_all_tile_configs(cfg: dict, install_root: Path) -> Dict[str, Dict[str, Any]]:
    raw = cfg.get(_FLOW_TILE_SLOTS_KEY) or {}
    out: Dict[str, Dict[str, Any]] = {}
    for tile_id in _DEFAULT_TILE_IDS:
        stored = raw.get(tile_id) or {}
        out[tile_id] = _normalize_tile(tile_id, stored if isinstance(stored, dict) else {}, install_root)
    return out


def get_tile_config(cfg: dict, tile_id: str, install_root: Path) -> Dict[str, Any]:
    return get_all_tile_configs(cfg, install_root)[tile_id]


def steps_from_tile(tile_cfg: Dict[str, Any]) -> List[FlowStep]:
    steps: List[FlowStep] = []
    raw = tile_cfg.get("steps") or []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("tool_id"):
                try:
                    steps.append(FlowStep.from_dict(item))
                except Exception:
                    continue
    if steps:
        return steps
    flow_id = str(tile_cfg.get("flow_id") or "").strip()
    if flow_id:
        flow = get_flow(flow_id)
        if flow and flow.steps:
            return list(flow.steps)
    return []


def flow_from_tile(tile_cfg: Dict[str, Any]) -> Optional[Flow]:
    steps = steps_from_tile(tile_cfg)
    if not steps:
        return None
    flow_id = str(tile_cfg.get("flow_id") or "").strip() or new_flow_id()
    return Flow(
        id=flow_id,
        name=str(tile_cfg.get("display_name") or "Flow"),
        steps=steps,
        output_mode=OUTPUT_MODE_HICO_PROCESSED,
        output_folder="",
        output_suffix="",
    )


def step_names(tile_cfg: Dict[str, Any]) -> List[str]:
    return [s.effective_label() for s in steps_from_tile(tile_cfg)]


def save_tile_config(cfg: dict, tile_id: str, tile_cfg: Dict[str, Any]) -> None:
    steps_payload = []
    for step in steps_from_tile(tile_cfg):
        steps_payload.append(step.to_dict())
    slots = dict(cfg.get(_FLOW_TILE_SLOTS_KEY) or {})
    from core.flow_run_paths import normalize_output_mode

    slots[tile_id] = {
        "display_name": tile_cfg.get("display_name", ""),
        "flow_id": tile_cfg.get("flow_id", ""),
        "steps": steps_payload,
        "override_global_output": bool(tile_cfg.get("override_global_output")),
        "flow_folder_name": safe_folder_name(
            str(tile_cfg.get("flow_folder_name") or "Flow"),
            "Flow",
        ) if tile_cfg.get("override_global_output") else "",
        "base_name_override": str(tile_cfg.get("base_name_override") or "") if tile_cfg.get("override_global_output") else "",
        "filename_pattern": str(tile_cfg.get("filename_pattern") or _DEFAULT_FILENAME_PATTERN) if tile_cfg.get("override_global_output") else "",
    }
    cfg[_FLOW_TILE_SLOTS_KEY] = slots
    cfgmod.save_config(cfg)


def tile_is_ready(tile_cfg: Dict[str, Any], cfg: Optional[dict] = None, install_root: Optional[Path] = None) -> bool:
    if not steps_from_tile(tile_cfg):
        return False
    from core.global_output_config import effective_flow_tile_cfg
    from core.flow_run_paths import normalize_output_mode, OUTPUT_MODE_IN_SOURCE, OUTPUT_MODE_CUSTOM

    eff = effective_flow_tile_cfg(cfg, tile_cfg, install_root) if cfg is not None else tile_cfg
    mode = normalize_output_mode(str(eff.get("output_mode") or OUTPUT_MODE_HICO_PROCESSED))
    if mode == OUTPUT_MODE_IN_SOURCE:
        return True
    if mode == OUTPUT_MODE_CUSTOM:
        return bool(str(eff.get("custom_output_folder") or "").strip())
    return bool(str(eff.get("output_root") or "").strip())


def expected_run_folder_hint(tile_cfg: Dict[str, Any], install_root: Path, cfg: Optional[dict] = None) -> str:
    from core.global_output_config import effective_flow_tile_cfg

    eff = effective_flow_tile_cfg(cfg, tile_cfg, install_root) if cfg is not None else tile_cfg
    from core.flow_run_paths import (
        normalize_output_mode,
        OUTPUT_MODE_IN_SOURCE,
        OUTPUT_MODE_CUSTOM,
        resolve_output_root,
        resolve_project_folder_name,
    )

    mode = normalize_output_mode(str(eff.get("output_mode") or OUTPUT_MODE_HICO_PROCESSED))
    if mode == OUTPUT_MODE_IN_SOURCE:
        return "(in source folder, flat filenames, no subfolder)"
    root = resolve_output_root(eff, install_root)
    folder = resolve_project_folder_name(eff)
    return str(root / folder / "Run_###")
