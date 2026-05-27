"""
Image I/O utilities — load with alpha awareness, save preserving EXIF where
appropriate, and decide output paths per the per-tool-subfolder strategy.
"""

from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# ---- Optional HEIC/HEIF support via pillow-heif ----
# If pillow-heif is installed, HEIC/HEIF files are decodable. If not,
# load_image_rgb_or_rgba will raise a clear error for those extensions.
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
    _HEIF_OK = True
except Exception:
    _HEIF_OK = False

_PIL_EXTS = {".heic", ".heif", ".avif"}

SUPPORTED_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".avif",
}


def _load_via_pil(path: Path) -> Tuple[np.ndarray, bool]:
    """Use PIL to load formats OpenCV can't handle (HEIC, HEIF, AVIF)."""
    from PIL import Image, ImageOps
    img = Image.open(str(path))
    # Honor EXIF orientation (iPhone photos rely on it)
    img = ImageOps.exif_transpose(img)
    if img.mode == "RGBA":
        return np.array(img, dtype=np.uint8), True
    if img.mode == "LA":
        img = img.convert("RGBA")
        return np.array(img, dtype=np.uint8), True
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img, dtype=np.uint8), False


def load_image_rgb_or_rgba(path: Path) -> Tuple[np.ndarray, bool]:
    """
    Load an image as a numpy array, RGB or RGBA.

    Returns (array, has_alpha). Array is uint8, shape HxWx3 or HxWx4.

    HEIC / HEIF / AVIF go through PIL (with pillow_heif if available).
    Everything else goes through OpenCV for speed and 16-bit support.
    """
    ext = path.suffix.lower()
    if ext in _PIL_EXTS:
        if ext in {".heic", ".heif"} and not _HEIF_OK:
            raise IOError(
                f"HEIC/HEIF support not installed. Run: pip install pillow-heif\n"
                f"(file: {path.name})"
            )
        try:
            return _load_via_pil(path)
        except Exception as e:
            raise IOError(f"Could not load {path.name}: {e}")

    import cv2
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        # Last-ditch fallback: try PIL for anything OpenCV refused
        try:
            return _load_via_pil(path)
        except Exception:
            raise IOError(f"Could not load image: {path}")
    # Normalize channel layout
    if raw.ndim == 2:
        # Grayscale -> RGB
        rgb = cv2.cvtColor(raw, cv2.COLOR_GRAY2RGB)
        return rgb, False
    if raw.shape[2] == 4:
        # BGRA -> RGBA
        rgba = cv2.cvtColor(raw, cv2.COLOR_BGRA2RGBA)
        return rgba, True
    if raw.shape[2] == 3:
        # BGR -> RGB
        rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
        return rgb, False
    # Anything weirder, force to 3 channels via OpenCV
    rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    return rgb, False


def save_image(array: np.ndarray, path: Path, has_alpha: bool, fmt: str = "png",
               jpg_quality: int = 95, webp_quality: int = 92) -> None:
    """
    Save a uint8 RGB or RGBA array. Format inferred from `fmt` or path suffix.
    Creates parent directory if missing.
    """
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "preserve":
        fmt = path.suffix.lstrip(".").lower() or "png"
    fmt = fmt.lower()

    # JPEG can't store alpha — composite onto white if needed
    if fmt in ("jpg", "jpeg") and has_alpha:
        # Composite onto white background
        alpha = array[..., 3:4].astype(np.float32) / 255.0
        rgb = array[..., :3].astype(np.float32)
        white = np.full_like(rgb, 255.0)
        composited = rgb * alpha + white * (1.0 - alpha)
        array = composited.clip(0, 255).astype(np.uint8)
        has_alpha = False

    # Convert to BGR(A) for OpenCV
    if has_alpha:
        out_bgra = cv2.cvtColor(array, cv2.COLOR_RGBA2BGRA)
    else:
        out_bgra = cv2.cvtColor(array[..., :3], cv2.COLOR_RGB2BGR)

    # Ensure correct extension
    target = path.with_suffix("." + ("jpg" if fmt == "jpeg" else fmt))

    if fmt in ("jpg", "jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, int(jpg_quality)]
    elif fmt == "webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, int(webp_quality)]
    elif fmt == "png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]  # fast-ish, good size
    else:
        params = []

    ok = cv2.imwrite(str(target), out_bgra, params)
    if not ok:
        raise IOError(f"cv2.imwrite failed for {target}")


def output_path_for(source: Path, tool_subfolder: str, suffix: str,
                    fmt: str = "png",
                    central_folder: Optional[Path] = None) -> Path:
    r"""
    Resolve where the processed file should land.

    Default (no central folder):
      source = /a/b/photo.jpg, tool_subfolder = "UltraSharp",
      suffix = "_x4_UltraSharp", fmt = "png"
      -> /a/b/UltraSharp/photo_x4_UltraSharp.png

    With central folder set (mirror-source-path-under-tool):
      source         = D:/Photos/2024/Vacation/IMG_1.jpg
      central_folder = D:/HicoForge_out
      tool_subfolder = "UltraSharp"
      -> D:/HicoForge_out/UltraSharp/Photos/2024/Vacation/IMG_1_x4_UltraSharp.png

    Path mirroring strategy: keep every component of the source's absolute
    path EXCEPT the drive/root, so the original folder tree is preserved
    inside the central tool subfolder. This is robust across drives
    (D:\Photos\… and C:\Pictures\… both work) without colliding.

    If a file already exists at the destination, appends -2, -3, ...
    """
    if fmt == "preserve":
        out_ext = source.suffix.lower().lstrip(".")
        if not out_ext:
            out_ext = "png"
    else:
        out_ext = ("jpg" if fmt == "jpeg" else fmt).lower()

    if central_folder is not None and str(central_folder).strip():
        central = Path(central_folder).expanduser()
        # Drop the drive/root, keep the rest of the source's parent chain.
        src_parent = source.resolve().parent
        try:
            rel_parts = src_parent.parts[1:]  # strip drive letter or '/'
        except Exception:
            rel_parts = ()
        subdir = central / tool_subfolder
        if rel_parts:
            subdir = subdir.joinpath(*rel_parts)
    else:
        subdir = source.parent / tool_subfolder

    base = source.stem + suffix
    candidate = subdir / f"{base}.{out_ext}"
    i = 2
    while candidate.exists():
        candidate = subdir / f"{base}-{i}.{out_ext}"
        i += 1
    return candidate
