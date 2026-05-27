"""
Spandrel-based image processor.

Handles every tool with processor_key == "spandrel_upscale":
  - All seven of the user's existing upscale/cleanup scripts
  - The new Real-ESRGAN, AnimeSharp tiles

Key fixes vs. the original scripts:
  * Model + tensor on the same device (no forced cpu/cuda mismatch)
  * No automatic ÷2 — output_scale is configurable per tile
  * Tiled inference for large images (avoids VRAM OOM)
  * Alpha channel preserved (RGBA path)
  * Output goes into per-tool subfolder via image_io.output_path_for
"""

from pathlib import Path
from typing import Optional, Callable

import numpy as np

from processors.base import BaseProcessor
from core import image_io


def _auto_tile_size(free_vram_mb: int, scale: int) -> int:
    """
    Pick a tile size that should fit comfortably. Conservative defaults
    that work on a 12 GB card; bigger cards get bigger tiles.
    """
    if free_vram_mb >= 20_000:
        return 1024
    if free_vram_mb >= 12_000:
        return 768
    if free_vram_mb >= 8_000:
        return 512
    if free_vram_mb >= 5_000:
        return 384
    return 256


def _run_tiled(model, np_rgb: np.ndarray, native_scale: int,
               tile: int, overlap: int, device: str,
               progress: Optional[Callable[[str], None]] = None) -> np.ndarray:
    """
    Tile-and-stitch inference. np_rgb is HxWx3 float32 in [0,1].
    Returns float32 HxWx3 (scaled by native_scale).
    """
    import torch

    h, w, _ = np_rgb.shape
    out_h, out_w = h * native_scale, w * native_scale
    output = np.zeros((out_h, out_w, 3), dtype=np.float32)
    weight = np.zeros((out_h, out_w, 1), dtype=np.float32)

    step = max(1, tile - overlap)
    n_tiles_y = (h + step - 1) // step
    n_tiles_x = (w + step - 1) // step
    total_tiles = n_tiles_y * n_tiles_x
    done = 0

    for ty in range(n_tiles_y):
        for tx in range(n_tiles_x):
            y0 = min(ty * step, max(0, h - tile))
            x0 = min(tx * step, max(0, w - tile))
            y1 = min(y0 + tile, h)
            x1 = min(x0 + tile, w)

            patch = np_rgb[y0:y1, x0:x1, :]
            # Pad to tile size if smaller (edge tiles)
            ph, pw = y1 - y0, x1 - x0
            if ph < tile or pw < tile:
                padded = np.zeros((tile, tile, 3), dtype=np.float32)
                padded[:ph, :pw, :] = patch
                patch = padded

            t = torch.from_numpy(patch).permute(2, 0, 1).unsqueeze(0)
            t = t.to(device)
            with torch.no_grad():
                out_t = model(t)
            out_t = out_t.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy()

            oy0, ox0 = y0 * native_scale, x0 * native_scale
            oy1, ox1 = y1 * native_scale, x1 * native_scale
            # Crop back to actual region (no padding in output)
            real_ph, real_pw = ph * native_scale, pw * native_scale
            out_patch = out_t[:real_ph, :real_pw, :]

            # Cosine-ramp blending for seamless seams
            blend = np.ones_like(out_patch[..., :1])
            ov = overlap * native_scale
            if ov > 0:
                if tx > 0:
                    ramp = np.linspace(0, 1, ov, dtype=np.float32)
                    blend[:, :ov, 0] = np.minimum(blend[:, :ov, 0], ramp[None, :])
                if ty > 0:
                    ramp = np.linspace(0, 1, ov, dtype=np.float32)
                    blend[:ov, :, 0] = np.minimum(blend[:ov, :, 0], ramp[:, None])
                if tx < n_tiles_x - 1 and (x0 + tile) < w:
                    ramp = np.linspace(1, 0, ov, dtype=np.float32)
                    end = real_pw
                    blend[:, max(0, end - ov):end, 0] = np.minimum(
                        blend[:, max(0, end - ov):end, 0], ramp[None, :]
                    )
                if ty < n_tiles_y - 1 and (y0 + tile) < h:
                    ramp = np.linspace(1, 0, ov, dtype=np.float32)
                    end = real_ph
                    blend[max(0, end - ov):end, :, 0] = np.minimum(
                        blend[max(0, end - ov):end, :, 0], ramp[:, None]
                    )

            output[oy0:oy1, ox0:ox1, :] += out_patch * blend
            weight[oy0:oy1, ox0:ox1, :] += blend

            done += 1
            if progress and (done % max(1, total_tiles // 8) == 0 or done == total_tiles):
                progress(f"tile {done}/{total_tiles}")

    # Normalize blend
    weight[weight == 0] = 1
    output /= weight
    return np.clip(output, 0, 1)


def _run_whole(model, np_rgb: np.ndarray, device: str) -> np.ndarray:
    import torch
    t = torch.from_numpy(np_rgb).permute(2, 0, 1).unsqueeze(0).to(device)
    with torch.no_grad():
        out = model(t)
    out = out.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy()
    return out


class SpandrelUpscaleProcessor(BaseProcessor):
    def process_one(self, source: Path,
                    progress: Optional[Callable[[str], None]] = None) -> Path:
        import cv2

        model_path = self._model_path()
        descriptor = self.ctx.model_cache.get(model_path)
        model = descriptor.model
        native_scale = getattr(descriptor, "scale", self.ctx.tool.native_scale) or 1

        device = "cuda" if self.ctx.gpu.available else "cpu"

        if progress:
            progress(f"Reading {source.name}…")
        img, has_alpha = image_io.load_image_rgb_or_rgba(source)

        rgb = img[..., :3].astype(np.float32) / 255.0
        alpha = img[..., 3:4] if has_alpha and self.ctx.preserve_alpha else None

        # Decide tile size
        tile = self.ctx.tile_size
        if tile <= 0:
            from core.gpu_info import refresh_free_vram
            refresh_free_vram(self.ctx.gpu)
            tile = _auto_tile_size(self.ctx.gpu.free_vram_mb or 8000, native_scale)

        h, w, _ = rgb.shape
        if max(h, w) <= tile:
            if progress:
                progress("Running model…")
            up_rgb = _run_whole(model, rgb, device)
        else:
            if progress:
                progress(f"Tiling ({tile}px)…")
            overlap = max(16, tile // 8)
            up_rgb = _run_tiled(model, rgb, native_scale, tile, overlap, device, progress)

        # Upscale alpha to match if present
        if alpha is not None:
            up_h, up_w, _ = up_rgb.shape
            up_alpha = cv2.resize(alpha, (up_w, up_h), interpolation=cv2.INTER_CUBIC)
            if up_alpha.ndim == 2:
                up_alpha = up_alpha[..., None]
            up_rgba = np.concatenate([up_rgb, up_alpha.astype(np.float32) / 255.0], axis=2)
        else:
            up_rgba = up_rgb

        # Apply user-requested output scale (relative to source, not model native)
        out_scale = float(self.ctx.output_scale)
        effective = up_rgba
        achieved_scale = native_scale  # how many x we currently are over source
        if abs(out_scale - achieved_scale) > 0.01 and out_scale > 0:
            target_w = max(1, int(round(w * out_scale)))
            target_h = max(1, int(round(h * out_scale)))
            interp = cv2.INTER_AREA if out_scale < achieved_scale else cv2.INTER_LANCZOS4
            effective = cv2.resize(up_rgba, (target_w, target_h), interpolation=interp)

        # Float -> uint8
        out_u8 = (effective * 255.0).clip(0, 255).astype(np.uint8)

        # Decide output path
        out_path = image_io.output_path_for(
            source=source,
            tool_subfolder=self.ctx.output_subfolder,
            suffix=self.ctx.output_suffix,
            fmt=self.ctx.output_format,
            central_folder=self.ctx.central_folder,
        )
        if progress:
            progress(f"Saving {out_path.name}…")
        image_io.save_image(
            out_u8,
            out_path,
            has_alpha=(out_u8.shape[-1] == 4),
            fmt=self.ctx.output_format,
            jpg_quality=self.ctx.jpg_quality,
            webp_quality=self.ctx.webp_quality,
        )
        return out_path
