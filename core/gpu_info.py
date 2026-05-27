"""
GPU / VRAM detection.

Safe to import even when torch is not installed yet — falls back to a
"CPU only" report so the UI can still launch.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class GPUInfo:
    available: bool                 # True if CUDA is usable
    device_name: str                # e.g. "NVIDIA GeForce RTX 5090" or "CPU"
    total_vram_mb: int              # 0 when CPU-only
    free_vram_mb: int               # 0 when CPU-only
    backend: str                    # "cuda" | "cpu"

    @property
    def used_vram_mb(self) -> int:
        return max(0, self.total_vram_mb - self.free_vram_mb)

    def short_label(self) -> str:
        if not self.available:
            return "CPU mode"
        gb_total = self.total_vram_mb / 1024
        # Use 1 decimal for sub-10 GB cards, no decimal for big ones
        fmt = f"{gb_total:.0f} GB" if gb_total >= 10 else f"{gb_total:.1f} GB"
        # Strip vendor noise for compact display
        name = self.device_name
        for prefix in ("NVIDIA ", "GeForce "):
            name = name.replace(prefix, "")
        return f"{name} · {fmt}"


def detect_gpu() -> GPUInfo:
    """Return a GPUInfo snapshot. Never raises."""
    try:
        import torch
    except Exception:
        return GPUInfo(False, "CPU (PyTorch not installed)", 0, 0, "cpu")

    if not torch.cuda.is_available():
        return GPUInfo(False, "CPU", 0, 0, "cpu")

    try:
        idx = 0
        name = torch.cuda.get_device_name(idx)
        props = torch.cuda.get_device_properties(idx)
        total = int(props.total_memory / (1024 * 1024))
        try:
            free_bytes, _total_bytes = torch.cuda.mem_get_info(idx)
            free = int(free_bytes / (1024 * 1024))
        except Exception:
            free = total
        return GPUInfo(True, name, total, free, "cuda")
    except Exception as e:
        return GPUInfo(False, f"CPU (CUDA error: {e})", 0, 0, "cpu")


def refresh_free_vram(info: GPUInfo) -> GPUInfo:
    """Refresh free VRAM only; cheap to call every few seconds."""
    if not info.available:
        return info
    try:
        import torch
        free_bytes, _total = torch.cuda.mem_get_info(0)
        info.free_vram_mb = int(free_bytes / (1024 * 1024))
    except Exception:
        pass
    return info
