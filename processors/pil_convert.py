"""
PIL-based format converter — the Convert Format utility tile.

Reads an image (using the same HEIC/AVIF-aware loader the upscalers use)
and writes it back in the user's chosen format. No model, no GPU, just
clean format conversion that handles transparency and EXIF orientation.

Output goes into a per-format subfolder next to the source:
  IMG_0072.HEIC + format=png  ->  ./Converted_PNG/IMG_0072.png
  photo.png     + format=jpg  ->  ./Converted_JPG/photo.jpg
  photo.png     + format=webp ->  ./Converted_WebP/photo.webp
  photo.png     + format=tiff ->  ./Converted_TIFF/photo.tiff

JPG never has alpha (composites onto white).
PNG/WebP/TIFF preserve alpha when present.
"""

from pathlib import Path
from typing import Optional, Callable

from processors.base import BaseProcessor
from core import image_io


# Subfolder names by output format
SUBFOLDER_BY_FMT = {
    "png":  "Converted_PNG",
    "jpg":  "Converted_JPG",
    "jpeg": "Converted_JPG",
    "webp": "Converted_WebP",
    "tiff": "Converted_TIFF",
    "tif":  "Converted_TIFF",
}


def subfolder_for_format(fmt: str) -> str:
    fmt = (fmt or "png").lower()
    return SUBFOLDER_BY_FMT.get(fmt, f"Converted_{fmt.upper()}")


class PilConvertProcessor(BaseProcessor):
    def process_one(self, source: Path,
                    progress: Optional[Callable[[str], None]] = None) -> Path:
        if progress:
            progress(f"Reading {source.name}…")

        img, has_alpha = image_io.load_image_rgb_or_rgba(source)

        # Resolve effective format. Tool default is "png"; user override
        # comes through ctx.output_format, which the factory pre-fills from
        # tool defaults + any per-tile setting overrides.
        fmt = (self.ctx.output_format or "png").lower()
        if fmt == "preserve":
            # For a "Convert" tile, "preserve" doesn't really make sense.
            # Fall back to PNG.
            fmt = "png"

        # Pick subfolder based on the chosen format, NOT the tool name.
        # This is the one place we override the factory's default subfolder.
        subfolder = subfolder_for_format(fmt)

        out_path = image_io.output_path_for(
            source=source,
            tool_subfolder=subfolder,
            suffix=self.ctx.output_suffix or "",
            fmt=fmt,
            central_folder=self.ctx.central_folder,
        )

        if progress:
            progress(f"Saving {out_path.name}…")

        image_io.save_image(
            img,
            out_path,
            has_alpha=has_alpha,
            fmt=fmt,
            jpg_quality=self.ctx.jpg_quality,
            webp_quality=self.ctx.webp_quality,
        )
        return out_path
