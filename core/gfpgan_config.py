"""
GFPGAN checkpoint → architecture profile resolution.

Does not import gfpgan/basicsr; uses spandrel GFPGAN arch classes + facexlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class GFPGANConfigError(Exception):
    pass


@dataclass(frozen=True)
class GFPGANProfile:
    version: str
    arch: str
    channel_multiplier: int
    upscale: int
    bg_upsampler: bool = False
    model_class: str = "GFPGANv1Clean"

    def cache_token(self) -> str:
        bg = "bg1" if self.bg_upsampler else "bg0"
        return (
            f"v={self.version}|arch={self.arch}|cm={self.channel_multiplier}|"
            f"up={self.upscale}|{bg}|cls={self.model_class}"
        )


_VERSION_FROM_NAME = re.compile(r"gfpganv?(\d+(?:\.\d+)?)", re.IGNORECASE)

_PROFILES: Dict[str, GFPGANProfile] = {
    "1.4": GFPGANProfile("1.4", "clean", 2, 1, False, "GFPGANv1Clean"),
    "1.3": GFPGANProfile("1.3", "clean", 2, 1, False, "GFPGANv1Clean"),
    "1.2": GFPGANProfile("1.2", "clean", 2, 1, False, "GFPGANv1Clean"),
    "1.0": GFPGANProfile("1.0", "original", 1, 1, False, "GFPGANv1"),
    "1": GFPGANProfile("1", "original", 1, 1, False, "GFPGANv1"),
}


def parse_version_from_filename(filename: str) -> Optional[str]:
    m = _VERSION_FROM_NAME.search(filename or "")
    if not m:
        return None
    ver = m.group(1)
    if ver == "1":
        return "1.0"
    return ver


def profile_for_filename(filename: str) -> GFPGANProfile:
    ver = parse_version_from_filename(filename)
    if ver and ver in _PROFILES:
        return _PROFILES[ver]
    raise GFPGANConfigError(
        f"Cannot determine GFPGAN architecture from checkpoint filename '{filename}'. "
        "Expected GFPGANv1.3.pth or GFPGANv1.4.pth (or GFPGANv1.2.pth / GFPGANv1.pth)."
    )


def _flatten_keys(state_dict: Dict[str, Any], limit: int = 80) -> str:
    return " ".join(list(state_dict.keys())[:limit]).lower()


def detect_foreign_checkpoint(state_dict: Dict[str, Any]) -> Optional[str]:
    """Return a label if the checkpoint is clearly not GFPGAN."""
    blob = _flatten_keys(state_dict)
    if "codeformer" in blob or "transformer.layers" in blob or "position_emb" in blob:
        return "CodeFormer"
    if "restoreformer" in blob or "encoder_layers" in blob and "toRGB" not in blob:
        return "RestoreFormer"
    if "gpen" in blob:
        return "GPEN"
    if "toRGB.0.weight" not in blob and "stylegan_decoder.style_mlp.1.weight" not in blob:
        if any(k in blob for k in ("body.", "conv_first", "upsample")):
            return "RealESRGAN/ESRGAN upscale model"
    return None


def extract_state_dict(checkpoint: Any) -> Dict[str, Any]:
    if not isinstance(checkpoint, dict):
        raise GFPGANConfigError("Checkpoint is not a dict — not a GFPGAN .pth file.")
    if "params_ema" in checkpoint:
        sd = checkpoint["params_ema"]
    elif "params" in checkpoint:
        sd = checkpoint["params"]
    elif "state_dict" in checkpoint:
        sd = checkpoint["state_dict"]
    else:
        sd = checkpoint
    if not isinstance(sd, dict) or not sd:
        raise GFPGANConfigError("Could not find GFPGAN weights (params_ema / params) in checkpoint.")
    return sd


def build_gfpgan_module(profile: GFPGANProfile):
    common = dict(
        out_size=512,
        num_style_feat=512,
        decoder_load_path=None,
        num_mlp=8,
        input_is_latent=True,
        different_w=True,
        narrow=1,
        sft_half=True,
        channel_multiplier=profile.channel_multiplier,
    )
    if profile.model_class == "GFPGANv1Clean":
        from spandrel.architectures.GFPGAN.__arch.gfpganv1_clean_arch import GFPGANv1Clean

        return GFPGANv1Clean(fix_decoder=False, **common)
    if profile.model_class == "GFPGANv1":
        from spandrel.architectures.GFPGAN.__arch.gfpganv1_arch import GFPGANv1

        return GFPGANv1(fix_decoder=True, **common)
    raise GFPGANConfigError(f"Unsupported GFPGAN model class: {profile.model_class}")


def load_gfpgan_weights(model_path: Path, profile: GFPGANProfile):
    import torch

    if not model_path.is_file():
        raise GFPGANConfigError(f"GFPGAN checkpoint not found: {model_path}")

    try:
        checkpoint = torch.load(str(model_path), map_location="cpu", weights_only=False)
    except TypeError:
        checkpoint = torch.load(str(model_path), map_location="cpu")

    state_dict = extract_state_dict(checkpoint)
    foreign = detect_foreign_checkpoint(state_dict)
    if foreign:
        raise GFPGANConfigError(
            f"Checkpoint '{model_path.name}' looks like {foreign}, not GFPGAN. "
            "Use GFPGANv1.4.pth or GFPGANv1.3.pth from the official GFPGAN release."
        )

    model = build_gfpgan_module(profile)
    try:
        model.load_state_dict(state_dict, strict=True)
    except RuntimeError as exc:
        raise GFPGANConfigError(
            f"GFPGAN checkpoint '{model_path.name}' does not match {profile.model_class} "
            f"(version={profile.version}, arch={profile.arch}, "
            f"channel_multiplier={profile.channel_multiplier}). "
            f"PyTorch load error: {exc}"
        ) from exc
    model.eval()
    return model


def resolve_profile_and_load(model_path: Path) -> Tuple[GFPGANProfile, Any]:
    profile = profile_for_filename(model_path.name)
    model = load_gfpgan_weights(model_path, profile)
    return profile, model
