"""
HicoForge tool registry — single source of truth for every tool in the app.

Each ToolDef describes one drop-zone tool: how it appears in the picker
(name, category, icon, description) and what processor backs it (filled in
in Chunk 3+). For now we only need the metadata so the picker and tile
widgets can render and store assignments.

To add a new tool later: append a ToolDef here. The picker and registry
helpers will pick it up automatically.
"""

from dataclasses import dataclass, field
from typing import Optional


# --- Categories ---
CAT_UPSCALE = "UPSCALE"
CAT_CLEANUP = "CLEANUP"
CAT_RESTORE = "RESTORE"
CAT_UTILITY = "UTILITY"

CATEGORY_ORDER = [CAT_UPSCALE, CAT_CLEANUP, CAT_RESTORE, CAT_UTILITY]

CATEGORY_COLOR = {
    CAT_UPSCALE: "#FFB347",   # ember gold
    CAT_CLEANUP: "#7DD3FC",   # cool blue (different feel from upscale heat)
    CAT_RESTORE: "#F87171",   # warm red (faces / repair)
    CAT_UTILITY: "#A78BFA",   # violet (transforms)
}


@dataclass
class ToolDef:
    """
    One tool that can be placed in a slot.

    Fields used in Chunk 2:
        id, name, category, description, glyph, model_filename, default_suffix,
        native_scale, default_output_scale

    Fields used in later chunks:
        processor_key (which processor class wires this up in Chunk 3+)
        default_settings (per-tile gear options in Chunk 7)
    """
    id: str
    name: str
    category: str
    description: str
    glyph: str                          # short emoji/character icon for the tile
    processor_key: str                  # which processor backend handles this
    model_filename: Optional[str] = None  # file inside the user's models folder
    download_url: Optional[str] = None    # direct download URL for the model file
    download_size_mb: Optional[int] = None  # approximate size, for the progress dialog
    download_sha256: Optional[str] = None   # known-good hash (verified after download). None = skip check.
    info_url: Optional[str] = None        # human-readable info / model card page
    native_scale: int = 1                 # 1x / 2x / 4x / 8x as trained
    default_output_scale: float = 1.0     # what the tile saves at by default
    default_suffix: str = ""              # appended to output filename
    default_format: str = "png"           # png / jpg / webp / preserve
    default_settings: dict = field(default_factory=dict)


# -------------------------------------------------------------------
# UPSCALE tools (spandrel-based)
# -------------------------------------------------------------------
UPSCALE_TOOLS = [
    ToolDef(
        id="ultrasharp_v1",
        name="UltraSharp",
        category=CAT_UPSCALE,
        description="The classic 4x UltraSharp model. Excellent on photos and everyday images. Use this if v2 isn't downloaded yet.",
        glyph="✦",
        processor_key="spandrel_upscale",
        model_filename="4x-UltraSharp.pth",
        download_url="https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth?download=true",
        download_size_mb=67,
        info_url="https://huggingface.co/Kim2091/UltraSharp",
        native_scale=4,
        default_output_scale=4.0,
        default_suffix="_x4_UltraSharp",
    ),
    ToolDef(
        id="ultrasharp_v2",
        name="UltraSharp v2",
        category=CAT_UPSCALE,
        description="General-purpose 4x sharp upscaler. The community-favorite all-rounder for photos, illustrations, and screenshots.",
        glyph="✦",
        processor_key="spandrel_upscale",
        model_filename="4x-UltraSharpV2.safetensors",
        download_url="https://huggingface.co/Kim2091/UltraSharpV2/resolve/main/4x-UltraSharpV2.safetensors?download=true",
        download_size_mb=140,
        info_url="https://huggingface.co/Kim2091/UltraSharpV2",
        native_scale=4,
        default_output_scale=4.0,
        default_suffix="_x4_UltraSharp",
    ),
    ToolDef(
        id="ultramix",
        name="Ultramix",
        category=CAT_UPSCALE,
        description="Balanced upscaler blending multiple model behaviors. Good when you don't know the source type.",
        glyph="◈",
        processor_key="spandrel_upscale",
        model_filename="4x-UltraMix_Balanced.pth",
        download_url="https://huggingface.co/utnah/esrgan/resolve/main/4x-UltraMix_Balanced.pth?download=true",
        download_size_mb=67,
        info_url="https://huggingface.co/utnah/esrgan",
        native_scale=4,
        default_output_scale=4.0,
        default_suffix="_Ultramix",
    ),
    ToolDef(
        id="purephoto",
        name="PurePhoto",
        category=CAT_UPSCALE,
        description="Photo-realistic upscaler. Preserves grain and natural texture without painterly smoothing.",
        glyph="◉",
        processor_key="spandrel_upscale",
        model_filename="4xPurePhoto-RealPLSKR.pth",
        download_url="https://huggingface.co/mp3pintyo/upscale/resolve/main/4xPurePhoto-RealPLSKR.pth?download=true",
        download_size_mb=30,
        info_url="https://openmodeldb.info/models/4x-PurePhoto-RealPLSKR",
        native_scale=4,
        default_output_scale=4.0,
        default_suffix="_x4_PurePhoto",
    ),
    ToolDef(
        id="tghqface8x",
        name="TGHQ Face 8x",
        category=CAT_UPSCALE,
        description="Specialized 8x upscaler for faces and portraits. Heavy facial detail enhancement. Best on close-ups.",
        glyph="☉",
        processor_key="spandrel_upscale",
        model_filename="TGHQFace8x_500k.pth",
        download_url="https://huggingface.co/RafaG/models-ESRGAN/resolve/main/TGHQFace8x_500k.pth?download=true",
        download_size_mb=67,
        info_url="https://openmodeldb.info/models/8x-TGHQFace-500000-G",
        native_scale=8,
        default_output_scale=8.0,
        default_suffix="_TGHQFace8x",
    ),
    ToolDef(
        id="countryroads",
        name="Country Roads 4x",
        category=CAT_UPSCALE,
        description="Landscape and outdoor photo upscaler. Trained on rural and nature imagery.",
        glyph="⛰",
        processor_key="spandrel_upscale",
        model_filename="4x_CountryRoads_377000_G.pth",
        download_url="https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x_CountryRoads_377000_G.pth?download=true",
        download_size_mb=67,
        info_url="https://openmodeldb.info/models/4x-CountryRoads",
        native_scale=4,
        default_output_scale=4.0,
        default_suffix="_x4_CountryRoads",
    ),
    ToolDef(
        id="realesrgan_x4plus",
        name="Real-ESRGAN 4x+",
        category=CAT_UPSCALE,
        description="Industry-default general-purpose 4x upscaler. Reliable fallback when other models overcook the image.",
        glyph="✧",
        processor_key="spandrel_upscale",
        model_filename="RealESRGAN_x4plus.pth",
        download_url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        native_scale=4,
        default_output_scale=4.0,
        default_suffix="_x4_RealESRGAN",
    ),
    ToolDef(
        id="anime_sharp",
        name="Anime Sharp 4x",
        category=CAT_UPSCALE,
        description="Dedicated anime and illustration upscaler. Crisp linework, clean flats.",
        glyph="✿",
        processor_key="spandrel_upscale",
        model_filename="4x-AnimeSharp.pth",
        download_url="https://huggingface.co/utnah/esrgan/resolve/main/4x-AnimeSharp.pth?download=true",
        download_size_mb=67,
        info_url="https://huggingface.co/Kim2091/AnimeSharp",
        native_scale=4,
        default_output_scale=4.0,
        default_suffix="_x4_AnimeSharp",
    ),
]

# -------------------------------------------------------------------
# CLEANUP tools (1x models — fix without rescale)
# -------------------------------------------------------------------
CLEANUP_TOOLS = [
    ToolDef(
        id="dither_deleter",
        name="Dither Deleter",
        category=CAT_CLEANUP,
        description="Removes dithering artifacts from old or indexed-color images. Not an upscaler — pure cleanup.",
        glyph="▦",
        processor_key="spandrel_upscale",
        model_filename="1x_DitherDeleterV3-Smooth-115000_G.pth",
        download_url="https://huggingface.co/sazoji/DitherDeleterV3-Smooth/resolve/main/1x_DitherDeleterV3-Smooth-115000_G.pth?download=true",
        download_size_mb=67,
        info_url="https://openmodeldb.info/models/1x-DitherDeleterV3-Smooth",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="_DitherDeleter",
    ),
    ToolDef(
        id="refocus_cleanly",
        name="Refocus Cleanly",
        category=CAT_CLEANUP,
        description="Sharpening and deblur pass. Fixes soft focus without rescaling.",
        glyph="◎",
        processor_key="spandrel_upscale",
        model_filename="1x_ReFocus_Cleanly_100000_G.pth",
        download_url="https://objectstorage.us-phoenix-1.oraclecloud.com/n/ax6ygfvpvzka/b/open-modeldb-files/o/1x-ReFocus-Cleanly.pth",
        download_size_mb=67,
        info_url="https://openmodeldb.info/models/1x-ReFocus-Cleanly",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="_Refocus",
    ),
    ToolDef(
        id="denoise_scunet",
        name="Denoise (SCUNet)",
        category=CAT_CLEANUP,
        description="True noise removal using SCUNet. Different from dither or refocus — targets grain and sensor noise.",
        glyph="〜",
        processor_key="spandrel_upscale",
        model_filename="scunet_color_real_psnr.pth",
        download_url="https://github.com/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth",
        download_size_mb=68,
        info_url="https://github.com/cszn/SCUNet",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="_Denoised",
    ),
    ToolDef(
        id="jpeg_artifact_fbcnn",
        name="JPEG Artifact (FBCNN)",
        category=CAT_CLEANUP,
        description="Removes JPEG compression artifacts. Run before upscaling on heavily compressed sources.",
        glyph="◇",
        processor_key="spandrel_upscale",
        model_filename="fbcnn_color.pth",
        download_url="https://github.com/jiaxi-jiang/FBCNN/releases/download/v1.0/fbcnn_color.pth",
        download_size_mb=263,
        info_url="https://github.com/jiaxi-jiang/FBCNN",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="_DeJPEG",
    ),
]

# -------------------------------------------------------------------
# RESTORE tools
# -------------------------------------------------------------------
RESTORE_TOOLS = [
    ToolDef(
        id="gfpgan_face",
        name="GFPGAN Face Restore",
        category=CAT_RESTORE,
        description="Restores damaged, blurry, or low-quality faces. Use before TGHQFace8x for best results on old photos.",
        glyph="☻",
        processor_key="spandrel_upscale",
        model_filename="GFPGANv1.4.pth",
        download_url="https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
        download_size_mb=333,
        info_url="https://github.com/TencentARC/GFPGAN",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="_FaceRestore",
    ),
]

# -------------------------------------------------------------------
# UTILITY tools (no AI model required)
# -------------------------------------------------------------------
UTILITY_TOOLS = [
    ToolDef(
        id="resize_to_spec",
        name="Resize",
        category=CAT_UTILITY,
        description="Resize to a target spec: 1080p, 2K, 4K, Instagram square, custom max dimension.",
        glyph="⤢",
        processor_key="pil_resize",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="_resized",
        default_settings={"target": "max_2048"},
    ),
    ToolDef(
        id="format_convert",
        name="Convert Format",
        category=CAT_UTILITY,
        description="Convert between PNG, JPG, WebP, TIFF. Reads HEIC/HEIF/AVIF too. Preserves transparency where supported.",
        glyph="⇄",
        processor_key="pil_convert",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="",
        default_format="png",
        default_settings={"target_format": "png", "jpg_quality": 95, "webp_quality": 92},
    ),
    ToolDef(
        id="bg_remove",
        name="Remove Background",
        category=CAT_UTILITY,
        description="Cuts out the subject, leaves transparent background. Powered by rembg / BiRefNet.",
        glyph="⬚",
        processor_key="rembg",
        native_scale=1,
        default_output_scale=1.0,
        default_suffix="_cutout",
        default_format="png",
    ),
]


# Single master list
ALL_TOOLS: list[ToolDef] = (
    UPSCALE_TOOLS + CLEANUP_TOOLS + RESTORE_TOOLS + UTILITY_TOOLS
)


# ---- Helpers ----

def get_tool(tool_id: str) -> Optional[ToolDef]:
    for t in ALL_TOOLS:
        if t.id == tool_id:
            return t
    return None


def tools_by_category() -> dict[str, list[ToolDef]]:
    out = {c: [] for c in CATEGORY_ORDER}
    for t in ALL_TOOLS:
        out.setdefault(t.category, []).append(t)
    return out


def search_tools(query: str) -> list[ToolDef]:
    """Case-insensitive substring search across name, description, category."""
    if not query:
        return list(ALL_TOOLS)
    q = query.lower().strip()
    matches = []
    for t in ALL_TOOLS:
        hay = f"{t.name} {t.description} {t.category} {t.id}".lower()
        if q in hay:
            matches.append(t)
    return matches
