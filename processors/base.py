"""
Base processor — common interface for every tile's image-processing backend.

Subclasses implement `process_one(source_path) -> output_path`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

from processors.tool_registry import ToolDef


@dataclass
class ProcessorContext:
    """Shared context handed to every processor on construction."""
    tool: ToolDef
    models_folder: Path
    model_cache: object              # ModelCache — typed as object to avoid cycles
    gpu: object                      # GPUInfo
    # Effective settings (start as tool defaults; per-tile overrides in Chunk 7)
    output_scale: float
    output_format: str               # png / jpg / webp / preserve
    output_suffix: str
    output_subfolder: str            # e.g. "UltraSharp"
    tile_size: int                   # 0 = auto
    preserve_alpha: bool
    jpg_quality: int = 95
    webp_quality: int = 92
    central_folder: Optional[Path] = None  # if set, outputs mirror source path under it
    # Resize-tool-only knobs (passed through factory; ignored by other processors)
    resize_target: Optional[str] = None        # e.g. 'max_2048', 'ig_square', 'custom'
    resize_custom_dim: int = 0                 # used when resize_target == 'custom'
    resize_allow_upscale: bool = False         # never grow images by default
    # rembg-only knob
    rembg_model: Optional[str] = None          # e.g. 'u2net', 'isnet', 'birefnet'


class BaseProcessor(ABC):
    def __init__(self, ctx: ProcessorContext):
        self.ctx = ctx

    @abstractmethod
    def process_one(self, source: Path,
                    progress: Optional[Callable[[str], None]] = None) -> Path:
        """Process one image. Must return the output file path."""
        ...

    # Helper used by spandrel-based processors
    def _model_path(self) -> Path:
        if not self.ctx.tool.model_filename:
            raise ValueError(f"Tool {self.ctx.tool.id} has no model_filename")
        return self.ctx.models_folder / self.ctx.tool.model_filename
