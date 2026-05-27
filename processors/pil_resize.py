"""
Resize utility processor — pure PIL/OpenCV, no model required.

Targets are spec-based, not free-form. The user picks one of:
  - 1080p (1920 long edge)
  - 2K    (2560 long edge)
  - 4K    (3840 long edge)
  - 8K    (7680 long edge)
  - Instagram square (1080x1080, center crop)
  - Custom max dimension

Resize semantics:
  - long-edge targets: scale so max(W,H) == target, preserve aspect
  - square: center-crop to a square, then resize to target
  - never upscale unless the user opts in (default: never upscale)

Output filename gets a suffix like _1080p / _2K / _IG / _max1024 plus the
tool's configured suffix.
"""

from pathlib import Path
from typing import Optional, Callable

import numpy as np

from processors.base import BaseProcessor
from core import image_io


# Built-in spec presets
SPEC_PRESETS = {
    "max_1080":  ("1080p", 1920, "long_edge"),
    "max_1440":  ("1440p", 2560, "long_edge"),
    "max_2048":  ("2K",    2048, "long_edge"),
    "max_2560":  ("2.5K",  2560, "long_edge"),
    "max_3840":  ("4K",    3840, "long_edge"),
    "max_7680":  ("8K",    7680, "long_edge"),
    "ig_square": ("IG",    1080, "square"),
}


def _suffix_for_target(target: str, custom_dim: int) -> str:
    if target == "custom":
        return f"_max{int(custom_dim)}"
    meta = SPEC_PRESETS.get(target)
    if not meta:
        return "_resized"
    short_name, _, _ = meta
    return f"_{short_name}"


def _compute_target_size(w: int, h: int, target: str, custom_dim: int,
                          allow_upscale: bool) -> tuple[int, int, str]:
    """Return (target_w, target_h, mode). mode is 'fit' or 'square'."""
    if target == "custom":
        dim = max(8, int(custom_dim))
        long_edge = max(w, h)
        if not allow_upscale and long_edge <= dim:
            return w, h, "fit"
        if w >= h:
            new_w = dim
            new_h = max(1, round(h * dim / w))
        else:
            new_h = dim
            new_w = max(1, round(w * dim / h))
        return new_w, new_h, "fit"

    meta = SPEC_PRESETS.get(target)
    if not meta:
        return w, h, "fit"
    _, dim, kind = meta

    if kind == "square":
        return dim, dim, "square"

    # long_edge
    long_edge = max(w, h)
    if not allow_upscale and long_edge <= dim:
        return w, h, "fit"
    if w >= h:
        new_w = dim
        new_h = max(1, round(h * dim / w))
    else:
        new_h = dim
        new_w = max(1, round(w * dim / h))
    return new_w, new_h, "fit"


class PilResizeProcessor(BaseProcessor):
    def process_one(self, source: Path,
                    progress: Optional[Callable[[str], None]] = None) -> Path:
        import cv2

        if progress:
            progress(f"Reading {source.name}…")

        img, has_alpha = image_io.load_image_rgb_or_rgba(source)
        h, w = img.shape[:2]

        # Pull settings from ctx.extra-ish: factory stuffs them into output_subfolder hack?
        # We follow the same pattern as pil_convert — read from tool defaults + overrides
        # through the ProcessorContext fields the factory already exposes.
        # `target` and `custom_dim` come from tool.default_settings merged with overrides
        # at factory time. They aren't standardized ProcessorContext fields, so we
        # stash them in ctx via a small extension: the factory passes them through
        # ctx.output_suffix? No — cleaner: pass via tool.default_settings + overrides
        # accessed through a per-tile lookup on ctx.tool.default_settings is wrong
        # (overrides won't appear). Instead, the factory writes resize settings into
        # ctx.output_suffix when explicit, and we accept that the live settings come
        # through the existing factory keys we already wired:
        #   - output_suffix (already set)
        # plus two new factory keys we'll add:
        #   - resize_target  -> stored on a new attr ctx.resize_target
        #   - resize_custom  -> ctx.resize_custom_dim
        target = getattr(self.ctx, "resize_target", None) \
            or (self.ctx.tool.default_settings or {}).get("target", "max_2048")
        custom_dim = int(getattr(self.ctx, "resize_custom_dim", 0)
                         or (self.ctx.tool.default_settings or {}).get("custom_dim", 2048))
        allow_upscale = bool(getattr(self.ctx, "resize_allow_upscale", False)
                             or (self.ctx.tool.default_settings or {}).get("allow_upscale", False))

        new_w, new_h, mode = _compute_target_size(
            w, h, target, custom_dim, allow_upscale
        )

        if progress:
            progress(f"Resizing {w}\u00d7{h} \u2192 {new_w}\u00d7{new_h}\u2026")

        # Square mode: center-crop to square first, then resize.
        if mode == "square":
            side = min(w, h)
            y0 = (h - side) // 2
            x0 = (w - side) // 2
            img = img[y0:y0 + side, x0:x0 + side]
            cur_h, cur_w = img.shape[:2]
            # Resize the square to target dim
            if (cur_w, cur_h) != (new_w, new_h):
                interp = cv2.INTER_AREA if new_w < cur_w else cv2.INTER_LANCZOS4
                img = cv2.resize(img, (new_w, new_h), interpolation=interp)
        else:
            # Fit mode
            if (new_w, new_h) != (w, h):
                interp = cv2.INTER_AREA if new_w < w else cv2.INTER_LANCZOS4
                img = cv2.resize(img, (new_w, new_h), interpolation=interp)

        # Resolve output format. "preserve" keeps source extension.
        fmt = (self.ctx.output_format or "preserve").lower()
        if fmt == "preserve":
            ext = source.suffix.lstrip(".").lower() or "png"
            fmt = "jpg" if ext == "jpeg" else ext

        # Build a meaningful suffix: tool's configured suffix + spec tag
        spec_suffix = _suffix_for_target(target, custom_dim)
        base_suffix = self.ctx.output_suffix or ""
        # Avoid double-suffixing if the user kept the default "_resized" suffix
        # AND a spec is selected, prefer just the spec tag.
        if base_suffix.strip().lower() in ("_resized", "resized", ""):
            final_suffix = spec_suffix
        else:
            final_suffix = base_suffix + spec_suffix

        out_path = image_io.output_path_for(
            source=source,
            tool_subfolder=self.ctx.output_subfolder,
            suffix=final_suffix,
            fmt=fmt,
            central_folder=self.ctx.central_folder,
        )

        if progress:
            progress(f"Saving {out_path.name}\u2026")

        # Resize may have produced a slightly different shape; recompute alpha flag
        final_has_alpha = (img.ndim == 3 and img.shape[-1] == 4) and has_alpha

        image_io.save_image(
            img,
            out_path,
            has_alpha=final_has_alpha,
            fmt=fmt,
            jpg_quality=self.ctx.jpg_quality,
            webp_quality=self.ctx.webp_quality,
        )
        return out_path
