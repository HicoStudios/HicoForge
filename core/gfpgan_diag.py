"""
Diagnostic logging for GFPGAN Face Restore runs.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.gfpgan_config import GFPGANProfile

_LOG_LOCK = threading.Lock()


def default_log_path() -> Path:
    return Path(__file__).resolve().parent.parent / "gfpgan_debug.log"


def log_gfpgan_event(event: str, **fields: Any) -> None:
    parts = [event] + [f"{k}={v}" for k, v in fields.items()]
    message = " | ".join(parts)
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} | {message}\n"
    print(f"[gfpgan] {message}")
    try:
        path = default_log_path()
        with _LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as exc:
        print(f"[gfpgan] log write failed: {exc}")


def log_load_context(
    *,
    tool_id: str,
    checkpoint_path: Path,
    profile: GFPGANProfile,
    device: str,
    dtype: str,
    input_dims: Optional[str] = None,
) -> None:
    size_bytes = checkpoint_path.stat().st_size if checkpoint_path.is_file() else 0
    log_gfpgan_event(
        "LOAD",
        tool_id=tool_id,
        checkpoint_path=str(checkpoint_path.resolve()),
        checkpoint_filename=checkpoint_path.name,
        checkpoint_size_bytes=size_bytes,
        gfpgan_version=profile.version,
        arch=profile.arch,
        channel_multiplier=profile.channel_multiplier,
        upscale=profile.upscale,
        bg_upsampler=profile.bg_upsampler,
        device=device,
        dtype=dtype,
        **({"input_dims": input_dims} if input_dims else {}),
    )


def log_inference_result(*, tool_id: str, elapsed_s: float, faces: int, output_dims: str) -> None:
    log_gfpgan_event(
        "INFERENCE",
        tool_id=tool_id,
        elapsed_s=f"{elapsed_s:.2f}",
        faces_detected=faces,
        output_dims=output_dims,
    )
