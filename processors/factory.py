"""
Processor factory — maps a tool's processor_key string to the right
processor class, builds the context, returns a ready-to-run instance.

Unknown processor keys (the not-yet-built ones from Chunk 5/6) raise a
clear error so the UI can surface "this tile's backend isn't ready yet."
"""

from pathlib import Path

from processors.base import BaseProcessor, ProcessorContext
from processors.tool_registry import ToolDef
from processors.spandrel_upscale import SpandrelUpscaleProcessor
from processors.pil_convert import PilConvertProcessor
from processors.pil_resize import PilResizeProcessor
from processors.rembg_processor import RemBGProcessor


# Map: processor_key -> processor class.
# SCUNet, FBCNN, and GFPGAN all reuse SpandrelUpscaleProcessor because
# spandrel 0.4+ ships native architecture support for them.
PROCESSOR_CLASSES = {
    "spandrel_upscale": SpandrelUpscaleProcessor,
    "pil_convert":      PilConvertProcessor,
    "pil_resize":       PilResizeProcessor,
    "rembg":            RemBGProcessor,
}


class UnsupportedProcessorError(Exception):
    pass


def build_processor(tool: ToolDef,
                    models_folder: Path,
                    model_cache,
                    gpu,
                    overrides: dict | None = None,
                    central_folder: Path | None = None) -> BaseProcessor:
    """
    Build a ready-to-run processor for `tool`.

    `overrides` lets per-tile settings (set via the gear icon and persisted
    in cfg['tile_settings']) override tool defaults.

    `central_folder` (from cfg['central_output_folder'] when non-empty) tells
    the processor to write outputs under <central>/<tool>/ mirroring the
    source's folder tree, instead of next-to-source.

    Supported override keys:
        target_format   -> output_format        (str: png/jpg/webp/tiff/preserve)
        output_format   -> output_format        (alias of target_format)
        jpg_quality     -> jpg_quality          (int 1-100)
        webp_quality    -> webp_quality         (int 1-100)
        output_scale    -> output_scale         (float)
        output_suffix   -> output_suffix        (str)
        tile_size       -> tile_size            (int, 0 = auto)
        preserve_alpha  -> preserve_alpha       (bool)
    """
    cls = PROCESSOR_CLASSES.get(tool.processor_key)
    if cls is None:
        raise UnsupportedProcessorError(
            f"Tool {tool.name}: backend '{tool.processor_key}' isn't wired up yet "
            f"(coming in a later chunk)."
        )

    overrides = overrides or {}
    settings = dict(tool.default_settings or {})
    settings.update(overrides)  # overrides win

    # Resolve output format
    fmt = settings.get("target_format") or settings.get("output_format") \
        or tool.default_format

    jpg_q = int(settings.get("jpg_quality", 95))
    webp_q = int(settings.get("webp_quality", 92))
    out_scale = float(settings.get("output_scale", tool.default_output_scale))
    suffix = settings.get("output_suffix", tool.default_suffix) or ""
    tile_size = int(settings.get("tile_size", 0))
    preserve_alpha = bool(settings.get("preserve_alpha", True))

    # Resize-only knobs (ignored by other processors)
    resize_target = settings.get("target")  # e.g. 'max_2048' / 'ig_square' / 'custom'
    resize_custom_dim = int(settings.get("custom_dim", 2048) or 2048)
    resize_allow_upscale = bool(settings.get("allow_upscale", False))

    # rembg-only knob
    rembg_model = settings.get("rembg_model")

    ctx = ProcessorContext(
        tool=tool,
        models_folder=models_folder,
        model_cache=model_cache,
        gpu=gpu,
        output_scale=out_scale,
        output_format=fmt,
        output_suffix=suffix,
        output_subfolder=tool.name.replace(" ", "_"),
        tile_size=tile_size,
        preserve_alpha=preserve_alpha,
        jpg_quality=jpg_q,
        webp_quality=webp_q,
        central_folder=central_folder,
        resize_target=resize_target,
        resize_custom_dim=resize_custom_dim,
        resize_allow_upscale=resize_allow_upscale,
        rembg_model=rembg_model,
    )
    return cls(ctx)
