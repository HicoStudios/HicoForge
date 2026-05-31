"""
Non-blocking Flow step-order guidance (face/restore after large upscalers).
"""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.flow_engine import Flow

_FACE_RESTORE_KEYWORDS = (
    "face",
    "tghq",
    "gfpgan",
    "codeformer",
    "restore",
)

# Step input above this megapixel count is "very large" for face/restore tools.
LARGE_FACE_INPUT_MPIX = 12.0


def _tool_text(tool_id: str, tool_name: str) -> str:
    return f"{tool_id} {tool_name}".lower()


def is_face_restore_tool(tool_id: str, tool_name: str = "") -> bool:
    text = _tool_text(tool_id, tool_name)
    return any(kw in text for kw in _FACE_RESTORE_KEYWORDS)


def is_large_upscaler_tool(tool_id: str, tool_name: str = "", native_scale: int = 1) -> bool:
    if native_scale >= 4:
        return True
    text = _tool_text(tool_id, tool_name)
    return any(kw in text for kw in ("ultrasharp", "ultramix", "purephoto", "animesharp", "countryroads", "real-esrgan", "esrgan"))


def face_after_upscale_message(upscaler_label: str, face_label: str) -> str:
    return (
        f"Step order note: '{face_label}' follows '{upscaler_label}' (large upscaler). "
        "Face/restore models may run faster before large 4x upscaling. "
        "Consider running TGHQ Face 8x before UltraSharp v2."
    )


def flow_step_order_warnings(flow: "Flow") -> List[str]:
    """Return human-readable warnings for risky face-after-upscale step orders."""
    warnings: List[str] = []
    if flow is None or not getattr(flow, "steps", None):
        return warnings

    from processors.tool_registry import get_tool

    steps = flow.steps
    for idx in range(1, len(steps)):
        step = steps[idx]
        tool = get_tool(step.tool_id)
        name = step.effective_label()
        if not is_face_restore_tool(step.tool_id, name):
            continue

        prev = steps[idx - 1]
        prev_tool = get_tool(prev.tool_id)
        prev_name = prev.effective_label()
        prev_scale = int(getattr(prev_tool, "native_scale", 1) or 1) if prev_tool else 1
        if not is_large_upscaler_tool(prev.tool_id, prev_name, prev_scale):
            continue

        msg = face_after_upscale_message(prev_name, name)
        if msg not in warnings:
            warnings.append(msg)
    return warnings
