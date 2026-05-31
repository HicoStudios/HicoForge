"""
VRAM diagnostics for Flow runs — logging only, no forced cleanup.

Log file: <install_root>/flow_vram_debug.log

Existing cleanup paths (not invoked automatically here except via step_release_fn):
  - MainWindow._unload_all_models() -> ModelCache.unload_all()
  - core.flow_model_cleanup.release_tool_model() -> ModelCache.unload()
  - ModelCache._free_descriptor() may call torch.cuda.empty_cache()
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SLOW_IMAGE_STEP_SEC = 120.0

_LOG_LOCK = threading.Lock()
_GPU_INFO = None


def megapixels(width: int, height: int) -> float:
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / 1_000_000.0


def format_dimensions(width: int, height: int) -> str:
    """Compact token-safe dimensions string for log fields."""
    return f"{width}x{height}/{megapixels(width, height):.2f}MP"


def read_image_dimensions(path: str | Path) -> Optional[tuple[int, int]]:
    """Read image width/height from header only (no full decode)."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        from PIL import Image

        with Image.open(p) as im:
            w, h = im.size
            return int(w), int(h)
    except Exception:
        return None


def reset_cuda_peak_memory_stats() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(0)
    except Exception:
        pass


def default_log_path() -> Path:
    return Path(__file__).resolve().parent.parent / "flow_vram_debug.log"


def _get_gpu_info():
    global _GPU_INFO
    if _GPU_INFO is None:
        try:
            from core.gpu_info import detect_gpu

            _GPU_INFO = detect_gpu()
        except Exception:
            _GPU_INFO = None
    return _GPU_INFO


def cuda_memory_mb() -> Dict[str, float]:
    """PyTorch CUDA memory counters in MB. Empty dict when unavailable."""
    out: Dict[str, float] = {}
    try:
        import torch

        if not torch.cuda.is_available():
            return out
        out["allocated_mb"] = torch.cuda.memory_allocated(0) / (1024 * 1024)
        out["reserved_mb"] = torch.cuda.memory_reserved(0) / (1024 * 1024)
        out["max_allocated_mb"] = torch.cuda.max_memory_allocated(0) / (1024 * 1024)
        out["max_reserved_mb"] = torch.cuda.max_memory_reserved(0) / (1024 * 1024)
    except Exception:
        pass
    return out


def vram_snapshot(loaded_models_fn: Optional[Callable[[], List[str]]] = None) -> Dict[str, Any]:
    """Combined driver + PyTorch + optional model-cache snapshot."""
    snap: Dict[str, Any] = {
        "cuda_available": False,
        "device_name": "",
        "driver_total_mb": 0,
        "driver_free_mb": 0,
        "driver_used_mb": 0,
        "allocated_mb": 0.0,
        "reserved_mb": 0.0,
        "max_allocated_mb": 0.0,
        "max_reserved_mb": 0.0,
        "models_loaded": [],
    }
    gpu = _get_gpu_info()
    if gpu is not None:
        try:
            from core.gpu_info import refresh_free_vram

            refresh_free_vram(gpu)
        except Exception:
            pass
        snap["cuda_available"] = bool(getattr(gpu, "available", False))
        snap["device_name"] = str(getattr(gpu, "device_name", "") or "")
        snap["driver_total_mb"] = int(getattr(gpu, "total_vram_mb", 0) or 0)
        snap["driver_free_mb"] = int(getattr(gpu, "free_vram_mb", 0) or 0)
        snap["driver_used_mb"] = int(getattr(gpu, "used_vram_mb", 0) or 0)

    snap.update(cuda_memory_mb())

    if loaded_models_fn is not None:
        try:
            snap["models_loaded"] = list(loaded_models_fn())
        except Exception as exc:
            snap["models_loaded"] = [f"(error: {exc})"]

    return snap


def format_snapshot(snap: Dict[str, Any]) -> str:
    models = snap.get("models_loaded") or []
    if isinstance(models, list):
        models_s = ",".join(str(m) for m in models) if models else "(none)"
    else:
        models_s = str(models)
    return (
        f"alloc={snap.get('allocated_mb', 0):.0f}MB "
        f"reserved={snap.get('reserved_mb', 0):.0f}MB "
        f"max_alloc={snap.get('max_allocated_mb', 0):.0f}MB "
        f"max_reserved={snap.get('max_reserved_mb', 0):.0f}MB "
        f"driver_used={snap.get('driver_used_mb', 0)}MB "
        f"driver_free={snap.get('driver_free_mb', 0)}MB "
        f"driver_total={snap.get('driver_total_mb', 0)}MB "
        f"models=[{models_s}]"
    )


class FlowVramLogger:
    """Append-only Flow VRAM diagnostic log."""

    def __init__(
        self,
        log_path: Optional[Path] = None,
        loaded_models_fn: Optional[Callable[[], List[str]]] = None,
    ) -> None:
        self._path = Path(log_path or default_log_path())
        self._loaded_models_fn = loaded_models_fn
        self._run_peak_max_alloc_mb = 0.0
        self._run_peak_max_reserved_mb = 0.0

    @property
    def log_path(self) -> Path:
        return self._path

    @property
    def run_peak_max_alloc_mb(self) -> float:
        return self._run_peak_max_alloc_mb

    @property
    def run_peak_max_reserved_mb(self) -> float:
        return self._run_peak_max_reserved_mb

    def snapshot(self) -> Dict[str, Any]:
        return vram_snapshot(self._loaded_models_fn)

    def note_run_peak_from_cuda(self) -> None:
        cm = cuda_memory_mb()
        self._run_peak_max_alloc_mb = max(
            self._run_peak_max_alloc_mb, float(cm.get("max_allocated_mb", 0.0) or 0.0)
        )
        self._run_peak_max_reserved_mb = max(
            self._run_peak_max_reserved_mb, float(cm.get("max_reserved_mb", 0.0) or 0.0)
        )

    def reset_step_peak_memory(self) -> None:
        """Reset per-step PyTorch peak counters; run-level peak is kept separately."""
        self.note_run_peak_from_cuda()
        reset_cuda_peak_memory_stats()

    def step_peak_mb(self) -> Dict[str, float]:
        return cuda_memory_mb()

    def _write(self, message: str) -> None:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} | {message}\n"
        try:
            with _LOG_LOCK:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
        except Exception as exc:
            print(f"[flow-vram] log write failed: {exc}")
        print(f"[flow-vram] {message}")

    def log_event(self, event: str, **fields: Any) -> None:
        snap = self.snapshot()
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        msg = f"{event} | {extra} | {format_snapshot(snap)}" if extra else f"{event} | {format_snapshot(snap)}"
        self._write(msg)

    def log_warning(self, warn_type: str, message: str, **fields: Any) -> None:
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        body = f"{message} | {extra}" if extra else message
        self._write(f"WARN {warn_type} | {body}")

    def log_dimensions(
        self,
        event: str,
        path: str,
        width: int,
        height: int,
        **fields: Any,
    ) -> None:
        name = Path(path).name if path else ""
        mp = megapixels(width, height)
        parts = [
            f"dims={width}x{height}",
            f"mp={mp:.2f}MP",
        ]
        if name:
            parts.append(f"file={name}")
        parts.extend(f"{k}={v}" for k, v in fields.items())
        self._write(f"{event} | {' '.join(parts)}")

    def log_run_start(
        self,
        *,
        flow_name: str,
        run_id: str,
        image_count: int,
        step_count: int,
        output_mode: str,
        execution_mode: str = "",
        **extra_fields: Any,
    ) -> None:
        snap = self.snapshot()
        extra = " ".join(f"{k}={v}" for k, v in extra_fields.items() if v)
        base = (
            f"RUN start | flow={flow_name} run_id={run_id} images={image_count} "
            f"steps={step_count} output_mode={output_mode} exec={execution_mode} "
            f"device={snap.get('device_name', '')}"
        )
        msg = f"{base} | {extra} | {format_snapshot(snap)}" if extra else f"{base} | {format_snapshot(snap)}"
        self._write(msg)

    def log_run_end(self, *, flow_name: str, run_id: str, images_ok: int, images_failed: int) -> None:
        self.note_run_peak_from_cuda()
        snap = self.snapshot()
        self._write(
            f"RUN end | flow={flow_name} run_id={run_id} ok={images_ok} "
            f"failed={images_failed} run_peak_max_alloc={self._run_peak_max_alloc_mb:.0f}MB "
            f"run_peak_max_reserved={self._run_peak_max_reserved_mb:.0f}MB "
            f"| {format_snapshot(snap)}"
        )

    def log_step_begin(self, step_idx: int, step_name: str, tool_id: str, image_count: int) -> None:
        self.reset_step_peak_memory()
        self.log_event(
            f"STEP {step_idx + 1} begin",
            tool=tool_id,
            name=step_name,
            images=image_count,
        )

    def log_step_end(
        self,
        step_idx: int,
        tool_id: str,
        image_count: int,
        ok_count: int,
        elapsed_s: float,
        *,
        step_peak_max_alloc_mb: float = 0.0,
        step_peak_max_reserved_mb: float = 0.0,
        dim_in: str = "",
        dim_out: str = "",
    ) -> None:
        self.note_run_peak_from_cuda()
        fields: Dict[str, Any] = {
            "tool": tool_id,
            "images": image_count,
            "ok": ok_count,
            "elapsed_s": f"{elapsed_s:.1f}",
            "step_peak_max_alloc": f"{step_peak_max_alloc_mb:.0f}MB",
            "step_peak_max_reserved": f"{step_peak_max_reserved_mb:.0f}MB",
            "run_peak_max_alloc": f"{self._run_peak_max_alloc_mb:.0f}MB",
            "run_peak_max_reserved": f"{self._run_peak_max_reserved_mb:.0f}MB",
        }
        if dim_in:
            fields["dim_in"] = dim_in
        if dim_out:
            fields["dim_out"] = dim_out
        self.log_event(f"STEP {step_idx + 1} end", **fields)

    def log_image(self, phase: str, step_idx: int, img_idx: int, image_count: int, source: str) -> None:
        name = Path(source).name if source else ""
        self.log_event(
            phase,
            step=step_idx + 1,
            img=f"{img_idx + 1}/{image_count}",
            file=name,
        )


def _parse_log_tokens(line: str) -> Dict[str, str]:
    tokens: Dict[str, str] = {}
    for part in line.split("|"):
        for token in part.strip().split():
            if "=" in token:
                key, val = token.split("=", 1)
                tokens[key] = val
    return tokens


def analyze_flow_vram_log(log_path: str | Path) -> Dict[str, Any]:
    """Parse flow_vram_debug.log and summarize the latest run."""
    path = Path(log_path)
    if not path.is_file():
        return {"error": f"log not found: {path}"}

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    run_start_idx = -1
    run_end_idx = -1
    run_id = ""
    execution_mode = ""
    for idx, line in enumerate(lines):
        if "RUN start |" in line:
            run_start_idx = idx
            tokens = _parse_log_tokens(line)
            run_id = tokens.get("run_id", run_id)
            execution_mode = tokens.get("exec", execution_mode)

    if run_start_idx < 0:
        return {"error": "no RUN start found in log", "log_path": str(path)}

    for idx in range(run_start_idx, len(lines)):
        if "RUN end |" in lines[idx]:
            run_end_idx = idx
            tokens = _parse_log_tokens(lines[idx])
            run_id = tokens.get("run_id", run_id)
            break

    segment = lines[run_start_idx : run_end_idx + 1 if run_end_idx >= 0 else None]
    report: Dict[str, Any] = {
        "log_path": str(path),
        "run_id": run_id,
        "execution_mode": execution_mode,
        "step_major_active": execution_mode == "structured_step_major",
        "steps": [],
        "warnings": [],
        "orig_inputs": [],
        "run_peak_max_alloc_mb": None,
        "run_peak_max_reserved_mb": None,
    }

    current_step: Optional[Dict[str, Any]] = None
    for line in segment:
        body = line.split("|", 1)[1].strip() if "|" in line else line.strip()

        if body.startswith("RUN end"):
            tokens = _parse_log_tokens(line)
            report["run_peak_max_alloc_mb"] = tokens.get("run_peak_max_alloc")
            report["run_peak_max_reserved_mb"] = tokens.get("run_peak_max_reserved")
            continue

        if body.startswith("WARN "):
            report["warnings"].append(body)
            continue

        if body.startswith("ORIG input"):
            report["orig_inputs"].append(body)
            continue

        if body.startswith("STEP ") and " begin" in body:
            step_num = body.split()[1]
            current_step = {
                "step": step_num,
                "begin": body,
                "end": "",
                "elapsed_s": None,
                "dim_in": "",
                "dim_out": "",
                "step_peak_max_alloc": "",
                "step_peak_max_reserved": "",
                "dims": [],
            }
            report["steps"].append(current_step)
            continue

        if body.startswith("STEP ") and " end" in body and current_step is not None:
            current_step["end"] = body
            tokens = _parse_log_tokens(line)
            current_step["elapsed_s"] = tokens.get("elapsed_s")
            current_step["dim_in"] = tokens.get("dim_in", "")
            current_step["dim_out"] = tokens.get("dim_out", "")
            current_step["step_peak_max_alloc"] = tokens.get("step_peak_max_alloc", "")
            current_step["step_peak_max_reserved"] = tokens.get("step_peak_max_reserved", "")
            continue

        if body.startswith("DIM ") and current_step is not None:
            current_step["dims"].append(body)

    return report


def format_flow_vram_report(report: Dict[str, Any]) -> str:
    if report.get("error"):
        return f"ERROR: {report['error']}"

    out: List[str] = []
    out.append(f"latest_run_id: {report.get('run_id') or '(unknown)'}")
    out.append(f"execution_mode: {report.get('execution_mode') or '(unknown)'}")
    out.append(
        "step_major_execution: "
        + ("active" if report.get("step_major_active") else "not detected")
    )
    if report.get("run_peak_max_alloc_mb"):
        out.append(
            f"run_peak: max_alloc={report['run_peak_max_alloc_mb']} "
            f"max_reserved={report.get('run_peak_max_reserved_mb', '')}"
        )

    if report.get("orig_inputs"):
        out.append("")
        out.append("original_input_dimensions:")
        for row in report["orig_inputs"]:
            out.append(f"  {row}")

    if report.get("steps"):
        out.append("")
        out.append("steps:")
        for step in report["steps"]:
            out.append(f"  Step {step.get('step')} elapsed_s={step.get('elapsed_s')}")
            if step.get("dim_in"):
                out.append(f"    dim_in: {step['dim_in']}")
            if step.get("dim_out"):
                out.append(f"    dim_out: {step['dim_out']}")
            if step.get("step_peak_max_alloc"):
                out.append(
                    f"    step_peak: alloc={step['step_peak_max_alloc']} "
                    f"reserved={step.get('step_peak_max_reserved', '')}"
                )
            for dim in step.get("dims") or []:
                out.append(f"    {dim}")

    warns = report.get("warnings") or []
    if warns:
        out.append("")
        out.append("warnings:")
        for w in warns:
            out.append(f"  {w}")
    else:
        out.append("")
        out.append("warnings: (none in latest run segment)")

    return "\n".join(out)

