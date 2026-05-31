"""
Safe model / VRAM helpers for Flow step-major batch runs.

Reuses ModelCache.unload() — the same path used by the title-bar Free VRAM button.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Tuple

from processors.tool_registry import get_tool


def model_path_for_tool(tool_id: str, models_folder: Path) -> Optional[Path]:
    tool = get_tool(tool_id)
    if tool is None or not tool.model_filename:
        return None
    return models_folder / tool.model_filename


def release_tool_model(model_cache, models_folder: Path, tool_id: str) -> bool:
    """Unload one tool's model from cache (spandrel and/or GFPGAN)."""
    released = False
    mp = model_path_for_tool(tool_id, models_folder)
    if mp is not None:
        try:
            released = bool(model_cache.unload(mp)) or released
        except Exception as exc:
            print(f"[flow] spandrel model release error for {tool_id}: {exc}")
    if tool_id == "gfpgan_face" or (get_tool(tool_id) and get_tool(tool_id).processor_key == "gfpgan"):
        try:
            from core.gfpgan_cache import get_gfpgan_cache

            if mp is not None:
                released = get_gfpgan_cache().unload(tool_id, mp) or released
        except Exception as exc:
            print(f"[flow] gfpgan cache release error for {tool_id}: {exc}")
    if mp is None:
        print(f"[flow] model release skipped (no model file): {tool_id}")
        return released
    state = "unloaded" if released else "not cached"
    print(f"[flow] model release {tool_id}: {state} ({mp.name})")
    return released


def vram_snapshot(gpu) -> str:
    if gpu is None or not getattr(gpu, "available", False):
        return "VRAM: n/a (CPU)"
    try:
        from core.gpu_info import refresh_free_vram

        refresh_free_vram(gpu)
        used = getattr(gpu, "used_vram_mb", 0)
        free = getattr(gpu, "free_vram_mb", 0)
        total = getattr(gpu, "total_vram_mb", 0)
        return f"VRAM used={used}MB free={free}MB total={total}MB"
    except Exception as exc:
        return f"VRAM: unreadable ({exc})"


def make_flow_step_callbacks(model_cache, gpu, cfg) -> Tuple[Callable[[str], None], Callable[[], str]]:
    models_folder = Path(str(cfg.get("models_folder") or ""))

    def release(tool_id: str) -> None:
        release_tool_model(model_cache, models_folder, tool_id)

    def vram() -> str:
        return vram_snapshot(gpu)

    return release, vram


def structured_execution_mode(image_count: int) -> str:
    """Structured Flow tile runs always use step-major order."""
    return "step_major"
