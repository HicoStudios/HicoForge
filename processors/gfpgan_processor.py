"""
GFPGAN Face Restore processor — uses facexlib face pipeline + matched GFPGAN weights.

Not a spandrel upscaler: detects/crops faces, restores at 512px, pastes back.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from core.gfpgan_cache import get_gfpgan_cache
from core.gfpgan_config import GFPGANConfigError
from core.gfpgan_diag import log_gfpgan_event, log_inference_result, log_load_context
from core import image_io
from processors.base import BaseProcessor


class GFPGANProcessor(BaseProcessor):
    def process_one(
        self,
        source: Path,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Path:
        import cv2

        skipped = self._maybe_skip_existing(source, progress)
        if skipped is not None:
            return skipped

        model_path = self._model_path()
        tool_id = self.ctx.tool.id

        if progress:
            progress(f"Reading {source.name}…")
        img, has_alpha = image_io.load_image_rgb_or_rgba(source)
        h, w = img.shape[:2]
        input_dims = f"{w}x{h}"

        bgr = cv2.cvtColor(img[..., :3], cv2.COLOR_RGB2BGR)

        try:
            cache = get_gfpgan_cache()
            if progress:
                progress("Loading GFPGAN…")
            runner = cache.get(tool_id, model_path, self.ctx.gpu)
        except GFPGANConfigError as exc:
            log_gfpgan_event("ERROR", tool_id=tool_id, checkpoint_path=str(model_path), error=str(exc))
            raise RuntimeError(str(exc)) from exc

        if progress:
            progress("Detecting and restoring faces…")
        t0 = time.perf_counter()
        restored_bgr, face_count = runner.enhance(bgr)
        elapsed = time.perf_counter() - t0

        out_h, out_w = restored_bgr.shape[:2]
        log_inference_result(
            tool_id=tool_id,
            elapsed_s=elapsed,
            faces=face_count,
            output_dims=f"{out_w}x{out_h}",
        )
        log_gfpgan_event(
            "RUN",
            tool_id=tool_id,
            checkpoint_path=str(model_path.resolve()),
            checkpoint_filename=model_path.name,
            input_dims=input_dims,
            output_dims=f"{out_w}x{out_h}",
            faces_detected=face_count,
        )

        if face_count == 0:
            log_gfpgan_event(
                "WARN",
                tool_id=tool_id,
                message="No faces detected — saving original image",
                input_dims=input_dims,
            )
            out_rgb = img[..., :3]
        else:
            out_rgb = cv2.cvtColor(restored_bgr, cv2.COLOR_BGR2RGB)
            if has_alpha and self.ctx.preserve_alpha:
                alpha = img[..., 3:4]
                out_rgb = np.concatenate([out_rgb, alpha], axis=2)

        out_u8 = out_rgb.astype(np.uint8) if out_rgb.dtype == np.uint8 else out_rgb.clip(0, 255).astype(np.uint8)

        out_path, plan_info = self._plan_output(source)
        if progress:
            progress(f"Saving {out_path.name}…")
        self._save_output_image(
            source,
            out_u8,
            out_path,
            plan_info,
            has_alpha=(out_u8.shape[-1] == 4),
            fmt=self.ctx.output_format,
            jpg_quality=self.ctx.jpg_quality,
            webp_quality=self.ctx.webp_quality,
        )
        return out_path
