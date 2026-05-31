"""
GFPGAN runner cache — separate from spandrel ModelCache.

Cache keys include tool_id, checkpoint path, filename, version, arch/config, device, dtype.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.gfpgan_config import GFPGANConfigError, GFPGANProfile, resolve_profile_and_load
from core.gfpgan_diag import log_load_context


@dataclass
class _GFPGANEntry:
    runner: "GFPGANRunner"
    last_used: float


class GFPGANRunner:
    """Face-detection + GFPGAN restore pipeline (GFPGANer-compatible, no basicsr)."""

    def __init__(self, model, profile: GFPGANProfile, device: str) -> None:
        import torch
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper
        from torchvision.transforms.functional import normalize

        self._profile = profile
        self._device = device
        self._normalize = normalize
        self.gfpgan = model.to(device)
        self.face_helper = FaceRestoreHelper(
            profile.upscale,
            face_size=512,
            crop_ratio=(1, 1),
            det_model="retinaface_resnet50",
            save_ext="png",
            use_parse=True,
            device=torch.device(device),
            model_rootpath=str(Path(__file__).resolve().parent.parent / "gfpgan_weights"),
        )
        self.bg_upsampler = None

    def _img2tensor(self, img_bgr):
        import cv2
        import torch

        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        t = torch.from_numpy(rgb.transpose(2, 0, 1)).float() / 255.0
        self._normalize(t, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), inplace=True)
        return t.unsqueeze(0).to(self._device)

    def _tensor2img(self, tensor):
        import cv2

        t = tensor.squeeze(0).float().cpu().clamp_(-1, 1)
        t = (t + 1) / 2
        rgb = (t.numpy().transpose(1, 2, 0) * 255.0).round().astype("uint8")
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def enhance(self, img_bgr, weight: float = 0.5):
        import torch

        self.face_helper.clean_all()
        self.face_helper.read_image(img_bgr)
        self.face_helper.get_face_landmarks_5(only_center_face=False, eye_dist_threshold=5)
        if not self.face_helper.cropped_faces:
            return img_bgr, 0
        self.face_helper.align_warp_face()

        for cropped_face in self.face_helper.cropped_faces:
            cropped_face_t = self._img2tensor(cropped_face)
            with torch.no_grad():
                output = self.gfpgan(cropped_face_t, return_rgb=False, weight=weight)[0]
            restored_face = self._tensor2img(output)
            self.face_helper.add_restored_face(restored_face)

        self.face_helper.get_inverse_affine(None)
        restored_img = self.face_helper.paste_faces_to_input_image(upsample_img=None)
        return restored_img, len(self.face_helper.cropped_faces)


class GFPGANCache:
    def __init__(self, max_loaded: int = 2) -> None:
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, _GFPGANEntry] = OrderedDict()
        self._max_loaded = max_loaded

    def _cache_key(
        self,
        tool_id: str,
        model_path: Path,
        profile: GFPGANProfile,
        device: str,
        dtype: str,
    ) -> str:
        resolved = str(model_path.resolve())
        return (
            f"tool={tool_id}|path={resolved}|file={model_path.name}|"
            f"{profile.cache_token()}|device={device}|dtype={dtype}"
        )

    def get(self, tool_id: str, model_path: Path, gpu) -> GFPGANRunner:
        device = "cuda" if getattr(gpu, "available", False) else "cpu"
        dtype = "float32"

        profile, model = resolve_profile_and_load(model_path)
        key = self._cache_key(tool_id, model_path, profile, device, dtype)

        with self._lock:
            if key in self._entries:
                entry = self._entries[key]
                entry.last_used = time.monotonic()
                self._entries.move_to_end(key)
                return entry.runner

        runner = GFPGANRunner(model, profile, device)
        log_load_context(
            tool_id=tool_id,
            checkpoint_path=model_path,
            profile=profile,
            device=device,
            dtype=dtype,
        )

        with self._lock:
            while len(self._entries) >= self._max_loaded:
                _, old_entry = self._entries.popitem(last=False)
                try:
                    del old_entry.runner
                except Exception:
                    pass
            self._entries[key] = _GFPGANEntry(runner, time.monotonic())
        return runner

    def unload(self, tool_id: str, model_path: Path) -> bool:
        resolved = str(model_path.resolve())
        removed = False
        with self._lock:
            to_drop = [k for k in self._entries if f"tool={tool_id}|" in k and f"path={resolved}|" in k]
            for k in to_drop:
                self._entries.pop(k, None)
                removed = True
        if removed:
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        return removed

    def unload_all(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        if n:
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        return n


_gfpgan_cache = GFPGANCache()


def get_gfpgan_cache() -> GFPGANCache:
    return _gfpgan_cache
