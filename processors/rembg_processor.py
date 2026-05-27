"""
Background removal via rembg.

rembg pulls a large dependency tree (onnxruntime + a ~170 MB u2net.onnx model)
the first time it's used. So we lazy-import inside process_one — the app
starts fine without rembg installed, and only blows up when a user actually
drops onto the Remove Background tile.

The first model run downloads the onnx weights into rembg's user cache
(usually ~/.u2net/). We don't manage that — let rembg do its thing.

Output is always RGBA PNG (the whole point is the cutout's alpha).
The Convert Format tile is the right downstream step if the user wants
to flatten the result onto a colored background.
"""

from pathlib import Path
from typing import Optional, Callable

import numpy as np

from processors.base import BaseProcessor
from core import image_io


# Friendly mapping of rembg model presets the user can pick.
# Keys are the values stored in tile settings; values are rembg's model name.
REMBG_MODELS = {
    "u2net":         "u2net",         # default, general-purpose
    "u2netp":        "u2netp",        # lighter / faster
    "u2net_human":   "u2net_human_seg",  # tuned for people
    "isnet":         "isnet-general-use",  # newer, often best quality
    "isnet_anime":   "isnet-anime",   # anime / illustration
    "silueta":       "silueta",       # ~43 MB, light alternative
    "birefnet":      "birefnet-general",  # heaviest, top quality
}


class RemBGProcessor(BaseProcessor):
    def process_one(self, source: Path,
                    progress: Optional[Callable[[str], None]] = None) -> Path:
        # Lazy-import so missing rembg doesn't break app launch
        try:
            from rembg import new_session, remove
        except ImportError as e:
            raise RuntimeError(
                "rembg isn't installed. In your project venv run:\n"
                "    pip install rembg onnxruntime\n"
                "(Use onnxruntime-gpu instead for CUDA acceleration.)"
            ) from e

        # Resolve which rembg model to use
        model_key = getattr(self.ctx, "rembg_model", None) \
            or (self.ctx.tool.default_settings or {}).get("rembg_model", "u2net")
        rembg_name = REMBG_MODELS.get(model_key, model_key)

        if progress:
            progress(f"Loading rembg model ({rembg_name})\u2026")

        # rembg caches sessions internally; new_session is cheap on subsequent calls
        try:
            session = new_session(rembg_name)
        except Exception as e:
            raise RuntimeError(
                f"Couldn't load rembg model '{rembg_name}': {e}\n"
                f"First run downloads weights into ~/.u2net/. Check network access."
            ) from e

        if progress:
            progress(f"Reading {source.name}\u2026")

        img, _has_alpha = image_io.load_image_rgb_or_rgba(source)

        # rembg.remove() works on either PIL.Image or numpy bytes/np.ndarray.
        # Easiest: feed the raw bytes via PIL, get back a PIL Image with alpha.
        from PIL import Image
        if img.shape[-1] == 4:
            pil_in = Image.fromarray(img, mode="RGBA")
        else:
            pil_in = Image.fromarray(img, mode="RGB")

        if progress:
            progress("Running cutout\u2026")
        try:
            pil_out = remove(pil_in, session=session)
        except Exception as e:
            raise RuntimeError(f"rembg failed on {source.name}: {e}") from e

        # Force RGBA — that's the whole purpose
        if pil_out.mode != "RGBA":
            pil_out = pil_out.convert("RGBA")
        out_np = np.array(pil_out, dtype=np.uint8)

        # Always save as RGBA PNG (transparency is the point)
        fmt = (self.ctx.output_format or "png").lower()
        if fmt in ("jpg", "jpeg"):
            # JPEG can't hold alpha — fall back to PNG and log a hint via progress
            if progress:
                progress("JPG can\u2019t hold alpha \u2014 saving PNG instead")
            fmt = "png"

        suffix = self.ctx.output_suffix or "_cutout"

        out_path = image_io.output_path_for(
            source=source,
            tool_subfolder=self.ctx.output_subfolder,
            suffix=suffix,
            fmt=fmt,
            central_folder=self.ctx.central_folder,
        )

        if progress:
            progress(f"Saving {out_path.name}\u2026")

        image_io.save_image(
            out_np,
            out_path,
            has_alpha=True,
            fmt=fmt,
            jpg_quality=self.ctx.jpg_quality,
            webp_quality=self.ctx.webp_quality,
        )
        return out_path
