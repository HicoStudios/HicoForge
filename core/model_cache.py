"""
Model cache.

Loads spandrel-compatible models lazily, keeps them in a small LRU cache,
optionally unloads them after an idle period to free VRAM. Thread-safe.

A model entry stores the spandrel descriptor so callers can use the
official `.scale` etc. metadata.
"""

import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Callable

from core.gpu_info import GPUInfo


class ModelCacheError(Exception):
    pass


class _Entry:
    __slots__ = ("descriptor", "device", "last_used")
    def __init__(self, descriptor, device: str):
        self.descriptor = descriptor
        self.device = device
        self.last_used = time.monotonic()


class ModelCache:
    def __init__(self, gpu: GPUInfo, max_loaded: int = 4,
                 idle_unload_seconds: int = 600,
                 status_callback: Optional[Callable[[str], None]] = None):
        self._gpu = gpu
        self._max_loaded = max_loaded
        self._idle_seconds = idle_unload_seconds
        self._status = status_callback or (lambda _msg: None)

        self._lock = threading.RLock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

        # Periodic idle sweep
        self._stop = threading.Event()
        self._sweeper = threading.Thread(target=self._sweep_loop, daemon=True)
        self._sweeper.start()

    # ---- Public API ----
    def get(self, model_path: Path):
        """Return the loaded descriptor for this path, loading on first use."""
        key = str(model_path.resolve())
        with self._lock:
            if key in self._entries:
                entry = self._entries[key]
                entry.last_used = time.monotonic()
                # Move to most-recently-used
                self._entries.move_to_end(key)
                return entry.descriptor

        # Load outside the lock — can be slow.
        descriptor, device = self._load(model_path)

        with self._lock:
            # Evict LRU if at capacity
            while len(self._entries) >= self._max_loaded:
                old_key, old_entry = self._entries.popitem(last=False)
                self._free_descriptor(old_entry.descriptor)
                self._status(f"Unloaded {Path(old_key).name} (cache full)")
            self._entries[key] = _Entry(descriptor, device)
            self._entries.move_to_end(key)
        return descriptor

    def unload(self, model_path: Path) -> bool:
        key = str(model_path.resolve())
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            return False
        self._free_descriptor(entry.descriptor)
        self._status(f"Unloaded {Path(key).name}")
        return True

    def unload_all(self) -> int:
        with self._lock:
            keys = list(self._entries.keys())
            entries = list(self._entries.values())
            self._entries.clear()
        for e in entries:
            self._free_descriptor(e.descriptor)
        if keys:
            self._status(f"Unloaded {len(keys)} model(s)")
        return len(keys)

    def loaded_names(self) -> list[str]:
        with self._lock:
            return [Path(k).name for k in self._entries.keys()]

    def shutdown(self):
        self._stop.set()
        self.unload_all()

    # ---- Internal ----
    def _load(self, model_path: Path):
        if not model_path.exists():
            raise ModelCacheError(f"Model file not found: {model_path}")
        try:
            from spandrel import ModelLoader
        except ImportError as e:
            raise ModelCacheError(
                "spandrel is not installed. Run: pip install spandrel"
            ) from e

        self._status(f"Loading {model_path.name}…")
        try:
            descriptor = ModelLoader().load_from_file(str(model_path))
        except Exception as e:
            raise ModelCacheError(f"Failed to load {model_path.name}: {e}") from e

        # Move to device + eval mode
        device = "cuda" if self._gpu.available else "cpu"
        try:
            descriptor.model.eval()
            descriptor.model.to(device)
            # half precision is faster on CUDA; spandrel models generally support fp32
            # so we leave dtype alone unless we know it's safe.
        except Exception as e:
            raise ModelCacheError(
                f"Could not move {model_path.name} to {device}: {e}"
            ) from e
        self._status(f"Loaded {model_path.name} on {device.upper()}")
        return descriptor, device

    def _free_descriptor(self, descriptor):
        try:
            descriptor.model.to("cpu")
        except Exception:
            pass
        try:
            del descriptor
        except Exception:
            pass
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _sweep_loop(self):
        while not self._stop.wait(30):
            now = time.monotonic()
            to_evict: list[str] = []
            with self._lock:
                for key, entry in self._entries.items():
                    if (now - entry.last_used) >= self._idle_seconds:
                        to_evict.append(key)
            for key in to_evict:
                self.unload(Path(key))
