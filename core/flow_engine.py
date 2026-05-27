"""
core/flow_engine.py
-------------------
Flow Tiles orchestrator for HicoForge v1.1.0.

Coordinates sequential multi-step processing chains (Flows) across one or
more source images.  Two run modes are supported:

  per_image  — image 1 completes all steps, then image 2, etc.
  per_stage  — all images pass through step 1, then all through step 2, etc.

Intermediate files are written to disk at every step using the naming
convention:
    {basename}_step01_{tool_id}.{ext}
    {basename}_step02_{tool_id}.{ext}
    ...
    {basename}_final.{ext}   (copy of the last successful step's output)

Reuses the existing JobQueue worker thread and build_processor() factory;
does NOT re-implement any image processing logic.

Qt signals are emitted on the main thread via QMetaObject.invokeMethod so
that connected UI widgets can update safely.
"""

from __future__ import annotations

import copy
import dataclasses
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, QMetaObject, Qt, Q_ARG, Slot

# build_processor is NOT imported here directly. The engine receives a
# `build_processor_fn(tool_id, overrides) -> BaseProcessor` callback at
# construction time (supplied by MainWindow). See BUILD_NOTES.md.
from processors.tool_registry import get_tool


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FlowStep:
    """A single step inside a Flow.

    Attributes
    ----------
    tool_id:
        Identifier matching a key in processors/tool_registry ALL_TOOLS.
    settings_override:
        Dict of settings values that override the tool's defaults at run-time.
        Empty dict means "use defaults".
    edit_before_run:
        When True the UI should open the per-tool settings dialog before this
        step executes.  FlowEngine itself does NOT open dialogs; it is the
        caller's responsibility to resolve overrides and pass them in via
        ``resolved_settings`` if this flag is set.
    label:
        Optional human-readable label for the step (shown in UI).
    """

    tool_id: str
    settings_override: Dict[str, Any] = dataclasses.field(default_factory=dict)
    edit_before_run: bool = False
    label: str = ""

    def effective_label(self) -> str:
        """Return label if set, otherwise fall back to the tool's display name."""
        if self.label:
            return self.label
        try:
            return get_tool(self.tool_id).name
        except Exception:
            return self.tool_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "settings_override": copy.deepcopy(self.settings_override),
            "edit_before_run": self.edit_before_run,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FlowStep":
        return cls(
            tool_id=d["tool_id"],
            settings_override=d.get("settings_override", {}),
            edit_before_run=d.get("edit_before_run", False),
            label=d.get("label", ""),
        )


OUTPUT_MODE_CUSTOM = "custom"          # write to flow.output_folder
OUTPUT_MODE_SOURCE_SUFFIX = "source_suffix"  # source dir + flow.output_suffix
OUTPUT_MODE_PER_RUN = "per_run"        # timestamped subfolder under output_folder
OUTPUT_MODE_LAST_USED = "last_used"    # remembered at runtime


@dataclasses.dataclass
class Flow:
    """Complete definition of a saved flow.

    Attributes
    ----------
    id:
        Short unique identifier, e.g. "flow_a1b2c3".
    name:
        Human-readable flow name.
    steps:
        Ordered list of FlowStep objects.
    output_mode:
        One of the OUTPUT_MODE_* constants above.
    output_folder:
        Absolute path string used when output_mode is OUTPUT_MODE_CUSTOM or
        OUTPUT_MODE_PER_RUN (base for subfolder).
    output_suffix:
        Appended to the source image directory name when output_mode is
        OUTPUT_MODE_SOURCE_SUFFIX.
    """

    id: str
    name: str
    steps: List[FlowStep] = dataclasses.field(default_factory=list)
    output_mode: str = OUTPUT_MODE_SOURCE_SUFFIX
    output_folder: str = ""
    output_suffix: str = "_flow_out"

    def step_preview(self, max_steps: int = 4) -> str:
        """One-line summary like 'UltraSharp → Convert → Refocus'."""
        labels = [s.effective_label() for s in self.steps[:max_steps]]
        suffix = f" +{len(self.steps) - max_steps}" if len(self.steps) > max_steps else ""
        return " → ".join(labels) + suffix

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
            "output_mode": self.output_mode,
            "output_folder": self.output_folder,
            "output_suffix": self.output_suffix,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Flow":
        return cls(
            id=d["id"],
            name=d["name"],
            steps=[FlowStep.from_dict(s) for s in d.get("steps", [])],
            output_mode=d.get("output_mode", OUTPUT_MODE_SOURCE_SUFFIX),
            output_folder=d.get("output_folder", ""),
            output_suffix=d.get("output_suffix", "_flow_out"),
        )


# ---------------------------------------------------------------------------
# Run-result types
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class StepResult:
    """Outcome of a single (image, step) pair."""
    step_idx: int
    tool_id: str
    input_path: str
    output_path: str
    success: bool
    error: str = ""


@dataclasses.dataclass
class ImageResult:
    """All step results for a single source image."""
    source_path: str
    final_path: str          # path to the _final.ext alias
    intermediates: List[str]  # ordered list of all step output paths
    step_results: List[StepResult] = dataclasses.field(default_factory=list)
    success: bool = True


# ---------------------------------------------------------------------------
# FlowEngine Qt object
# ---------------------------------------------------------------------------

class FlowEngine(QObject):
    """Orchestrates multi-step flow execution.

    All signals are emitted from the worker thread via invokeMethod so that
    Qt's queued connection delivers them on the main thread.

    Signals
    -------
    stepStarted(step_idx, total_steps, tool_id)
        Fired just before a step begins processing any image.
    stepProgress(step_idx, image_idx, pct)
        Fired periodically while a step processes an image (0–100).
    imageDone(source_path, final_path, intermediates_json)
        Fired when a source image has completed all steps.
        intermediates_json is a JSON-encoded list of paths.
    flowFinished(summary_json)
        Fired when the entire flow completes.  summary_json encodes a dict
        with keys: images_ok, images_failed, total_steps_run.
    flowError(err_msg)
        Fired on unrecoverable errors (e.g. no steps defined).
    """

    stepStarted = Signal(int, int, str)          # step_idx, total_steps, tool_id
    stepProgress = Signal(int, int, int)         # step_idx, image_idx, pct
    imageDone = Signal(str, str, str)            # source_path, final_path, intermediates_json
    flowFinished = Signal(str)                   # summary_json
    flowError = Signal(str)                      # err_msg

    def __init__(
        self,
        build_processor_fn: Callable[[str, Dict[str, Any]], Any],
        parent: Optional[QObject] = None,
    ) -> None:
        """
        Parameters
        ----------
        build_processor_fn:
            Callable(tool_id, overrides_dict) -> BaseProcessor.
            The host (MainWindow) supplies this so the engine never has to
            know about models_folder / model_cache / gpu / central_folder.
            Mirrors the JobQueue pattern.
        """
        super().__init__(parent)
        self._build_processor_fn = build_processor_fn
        self._running = False
        self._abort = False
        self._last_output_folder: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_flow(
        self,
        flow: Flow,
        source_paths: List[str],
        mode: str = "per_image",
        resolved_settings: Optional[Dict[int, Dict[str, Any]]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        finished_callback: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        """Start the flow in a background thread.

        Parameters
        ----------
        flow:
            The Flow definition to execute.
        source_paths:
            List of absolute paths to source images.
        mode:
            'per_image' or 'per_stage'.
        resolved_settings:
            Dict mapping step index → settings dict.  Use this to pass
            settings resolved by the UI for steps whose edit_before_run is
            True.  Keys absent here fall back to step.settings_override.
        progress_callback:
            Optional callable(message: str) called with human-readable status
            updates from the worker thread.
        finished_callback:
            Optional callable(summary: dict) called when the flow completes.
        """
        if self._running:
            print("[flow] run_flow called while already running — ignoring")
            return
        if not flow.steps:
            self._emit_error("Flow has no steps defined.")
            return
        if not source_paths:
            self._emit_error("No source images provided.")
            return

        self._running = True
        self._abort = False

        t = threading.Thread(
            target=self._worker,
            args=(flow, source_paths, mode, resolved_settings or {}, progress_callback, finished_callback),
            daemon=True,
            name=f"FlowEngine-{flow.id}",
        )
        t.start()

    def abort(self) -> None:
        """Request the running flow to stop after the current step/image."""
        self._abort = True

    # ------------------------------------------------------------------
    # Output path helpers
    # ------------------------------------------------------------------

    def _resolve_output_dir(self, flow: Flow, source_path: str) -> Path:
        """Determine the output directory for a given flow + source image."""
        src = Path(source_path)

        if flow.output_mode == OUTPUT_MODE_CUSTOM:
            base = Path(flow.output_folder) if flow.output_folder else src.parent
            return base

        elif flow.output_mode == OUTPUT_MODE_SOURCE_SUFFIX:
            suffix = flow.output_suffix or "_flow_out"
            return src.parent / (src.parent.name + suffix)

        elif flow.output_mode == OUTPUT_MODE_PER_RUN:
            base = Path(flow.output_folder) if flow.output_folder else src.parent
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in flow.name)
            return base / f"{safe_name}_{stamp}"

        elif flow.output_mode == OUTPUT_MODE_LAST_USED:
            if self._last_output_folder:
                return Path(self._last_output_folder)
            return src.parent

        # fallback
        return src.parent

    def _step_output_path(
        self,
        output_dir: Path,
        basename: str,
        step_idx: int,
        tool_id: str,
        ext: str,
    ) -> Path:
        """Build the intermediate output path for a step."""
        safe_tool = tool_id.replace(" ", "_").replace("/", "-")
        stem = f"{basename}_step{step_idx + 1:02d}_{safe_tool}"
        return output_dir / f"{stem}{ext}"

    def _final_path(self, output_dir: Path, basename: str, ext: str) -> Path:
        return output_dir / f"{basename}_final{ext}"

    def _effective_settings(
        self,
        step: FlowStep,
        step_idx: int,
        resolved_settings: Dict[int, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge tool defaults → step override → resolved (UI-supplied) settings."""
        try:
            tool = get_tool(step.tool_id)
            base = dict(tool.default_settings) if hasattr(tool, "default_settings") else {}
        except Exception:
            base = {}

        base.update(step.settings_override)
        if step_idx in resolved_settings:
            base.update(resolved_settings[step_idx])
        return base

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _worker(
        self,
        flow: Flow,
        source_paths: List[str],
        mode: str,
        resolved_settings: Dict[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str], None]],
        finished_callback: Optional[Callable[[Dict], None]],
    ) -> None:
        """Background worker — runs the full flow."""
        try:
            if mode == "per_image":
                results = self._run_per_image(flow, source_paths, resolved_settings, progress_callback)
            else:
                results = self._run_per_stage(flow, source_paths, resolved_settings, progress_callback)
        except Exception as exc:
            import traceback
            msg = f"Flow engine unhandled exception: {exc}\n{traceback.format_exc()}"
            print(f"[flow] {msg}")
            self._emit_error(msg)
            self._running = False
            return

        images_ok = sum(1 for r in results if r.success)
        images_failed = len(results) - images_ok
        total_steps_run = sum(len(r.step_results) for r in results)
        summary = {
            "flow_id": flow.id,
            "flow_name": flow.name,
            "images_ok": images_ok,
            "images_failed": images_failed,
            "total_steps_run": total_steps_run,
            "image_results": [
                {
                    "source": r.source_path,
                    "final": r.final_path,
                    "intermediates": r.intermediates,
                }
                for r in results
            ],
        }

        if finished_callback:
            try:
                finished_callback(summary)
            except Exception as e:
                print(f"[flow] finished_callback raised: {e}")

        import json
        summary_json = json.dumps(summary)
        self._emit_flow_finished(summary_json)
        self._running = False

    # ------------------------------------------------------------------
    # per_image mode
    # ------------------------------------------------------------------

    def _run_per_image(
        self,
        flow: Flow,
        source_paths: List[str],
        resolved_settings: Dict[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str], None]],
    ) -> List[ImageResult]:
        results: List[ImageResult] = []
        total_steps = len(flow.steps)

        for img_idx, src in enumerate(source_paths):
            if self._abort:
                break
            result = self._process_image(
                flow, src, img_idx, len(source_paths), total_steps,
                resolved_settings, progress_callback,
            )
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # per_stage mode
    # ------------------------------------------------------------------

    def _run_per_stage(
        self,
        flow: Flow,
        source_paths: List[str],
        resolved_settings: Dict[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str], None]],
    ) -> List[ImageResult]:
        total_steps = len(flow.steps)
        n_images = len(source_paths)

        # Build output dirs and basenames for each source image up front
        output_dirs: List[Path] = []
        basenames: List[str] = []
        for src in source_paths:
            p = Path(src)
            od = self._resolve_output_dir(flow, src)
            od.mkdir(parents=True, exist_ok=True)
            self._last_output_folder = str(od)
            output_dirs.append(od)
            basenames.append(p.stem)

        # current_inputs[i] = path to feed as input for image i in next step
        current_inputs: List[str] = list(source_paths)

        # Accumulate per-image data
        image_step_results: List[List[StepResult]] = [[] for _ in source_paths]
        image_intermediates: List[List[str]] = [[] for _ in source_paths]

        for step_idx, step in enumerate(flow.steps):
            if self._abort:
                break

            settings = self._effective_settings(step, step_idx, resolved_settings)
            self._emit_step_started(step_idx, total_steps, step.tool_id)

            # Build a fresh processor per (step, image) so per-image overrides
            # (suffix containing step number, format matching source) take effect.
            # Note: we DO NOT pre-build once per step — build is cheap; the model
            # is loaded lazily inside the processor and cached by model_cache.

            for img_idx, src in enumerate(source_paths):
                if self._abort:
                    break

                ext = Path(current_inputs[img_idx]).suffix or ".png"
                out_path = self._step_output_path(
                    output_dirs[img_idx], basenames[img_idx], step_idx, step.tool_id, ext
                )
                out_path.parent.mkdir(parents=True, exist_ok=True)

                msg = f"Step {step_idx + 1}/{total_steps}: {step.effective_label()} · img {img_idx + 1}/{n_images}"
                if progress_callback:
                    try:
                        progress_callback(msg)
                    except Exception:
                        pass

                self._emit_step_progress(step_idx, img_idx, 0)
                success, err, actual_out = self._run_one(
                    step.tool_id, current_inputs[img_idx], out_path, settings,
                )
                if success and actual_out and actual_out != out_path:
                    # Move processor's output to our canonical step path
                    try:
                        if out_path.exists():
                            out_path.unlink()
                        shutil.move(str(actual_out), str(out_path))
                    except Exception as mv_err:
                        print(f"[flow] move {actual_out} -> {out_path} failed: {mv_err}")
                        out_path = actual_out  # fall back to wherever the processor wrote
                self._emit_step_progress(step_idx, img_idx, 100)

                sr = StepResult(
                    step_idx=step_idx,
                    tool_id=step.tool_id,
                    input_path=current_inputs[img_idx],
                    output_path=str(out_path) if success else "",
                    success=success,
                    error=err,
                )
                image_step_results[img_idx].append(sr)
                if success:
                    image_intermediates[img_idx].append(str(out_path))
                    current_inputs[img_idx] = str(out_path)
                else:
                    if err and "build_processor" in err:
                        # Backend not wired up — don't keep trying remaining images for this step
                        for j in range(img_idx + 1, n_images):
                            image_step_results[j].append(StepResult(
                                step_idx=step_idx,
                                tool_id=step.tool_id,
                                input_path=current_inputs[j],
                                output_path="",
                                success=False,
                                error=err,
                            ))
                        break

        # Finalise each image
        results: List[ImageResult] = []
        for img_idx, src in enumerate(source_paths):
            intermediates = image_intermediates[img_idx]
            overall_success = any(sr.success for sr in image_step_results[img_idx])
            final_p = ""
            if intermediates:
                ext = Path(intermediates[-1]).suffix
                fp = self._final_path(output_dirs[img_idx], basenames[img_idx], ext)
                try:
                    shutil.copy2(intermediates[-1], fp)
                    final_p = str(fp)
                except Exception as e:
                    print(f"[flow] Failed to write _final for {src}: {e}")

            ir = ImageResult(
                source_path=src,
                final_path=final_p,
                intermediates=intermediates,
                step_results=image_step_results[img_idx],
                success=overall_success,
            )
            results.append(ir)

            import json
            self._emit_image_done(src, final_p, json.dumps(intermediates))

        return results

    # ------------------------------------------------------------------
    # Core per-image processing (used by per_image mode)
    # ------------------------------------------------------------------

    def _process_image(
        self,
        flow: Flow,
        src: str,
        img_idx: int,
        total_images: int,
        total_steps: int,
        resolved_settings: Dict[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str], None]],
    ) -> ImageResult:
        """Run all steps on a single source image and return ImageResult."""
        src_path = Path(src)
        output_dir = self._resolve_output_dir(flow, src)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[flow] Could not create output dir {output_dir}: {e}")
            return ImageResult(source_path=src, final_path="", intermediates=[], success=False)

        self._last_output_folder = str(output_dir)
        basename = src_path.stem
        current_input = src
        intermediates: List[str] = []
        step_results: List[StepResult] = []

        for step_idx, step in enumerate(flow.steps):
            if self._abort:
                break

            settings = self._effective_settings(step, step_idx, resolved_settings)
            self._emit_step_started(step_idx, total_steps, step.tool_id)

            ext = Path(current_input).suffix or ".png"
            out_path = self._step_output_path(output_dir, basename, step_idx, step.tool_id, ext)

            msg = (
                f"Step {step_idx + 1}/{total_steps}: {step.effective_label()} "
                f"· img {img_idx + 1}/{total_images}"
            )
            if progress_callback:
                try:
                    progress_callback(msg)
                except Exception:
                    pass

            self._emit_step_progress(step_idx, img_idx, 0)
            success, err, actual_out = self._run_one(
                step.tool_id, current_input, out_path, settings,
            )
            if success and actual_out and actual_out != out_path:
                try:
                    if out_path.exists():
                        out_path.unlink()
                    shutil.move(str(actual_out), str(out_path))
                except Exception as mv_err:
                    print(f"[flow] move {actual_out} -> {out_path} failed: {mv_err}")
                    out_path = actual_out
            self._emit_step_progress(step_idx, img_idx, 100)

            sr = StepResult(
                step_idx=step_idx,
                tool_id=step.tool_id,
                input_path=current_input,
                output_path=str(out_path) if success else "",
                success=success,
                error=err,
            )
            step_results.append(sr)

            if success:
                intermediates.append(str(out_path))
                current_input = str(out_path)
            else:
                print(f"[flow] Step {step_idx + 1} ({step.tool_id}) failed on {src}: {err}")
                # Keep going with same current_input

        # Write _final alias
        final_p = ""
        if intermediates:
            ext = Path(intermediates[-1]).suffix
            fp = self._final_path(output_dir, basename, ext)
            try:
                shutil.copy2(intermediates[-1], fp)
                final_p = str(fp)
            except Exception as e:
                print(f"[flow] Failed to write _final for {src}: {e}")

        overall_success = any(sr.success for sr in step_results)
        ir = ImageResult(
            source_path=src,
            final_path=final_p,
            intermediates=intermediates,
            step_results=step_results,
            success=overall_success,
        )

        import json
        self._emit_image_done(src, final_p, json.dumps(intermediates))
        return ir

    # ------------------------------------------------------------------
    # Processor execution (isolated for error handling)
    # ------------------------------------------------------------------

    def _run_one(
        self,
        tool_id: str,
        input_path: str,
        desired_out_path: Path,
        settings: Dict[str, Any],
    ) -> tuple[bool, str, Optional[Path]]:
        """
        Build a processor for `tool_id` with overrides steered to land output
        as close to `desired_out_path` as possible, run `.process_one(source)`,
        and return (success, error, actual_output_path).

        The processor decides its own output path based on its context
        (output_suffix, output_subfolder, central_folder). We pass an override
        suffix matching desired_out_path.stem so the processor writes a
        predictable filename; the caller moves the file to the final location
        if the directories differ.
        """
        try:
            # Compose overrides: start from step settings, then force suffix +
            # output_format so processor writes a file we can identify.
            overrides = dict(settings or {})
            src_p = Path(input_path)
            # The processor names outputs as: <source_stem><output_suffix>.<output_format>
            # We want: <desired_out_path.stem>.<desired_out_path.suffix>
            # So set output_suffix to (desired_stem - source_stem) if desired starts with source stem,
            # otherwise force suffix = full desired stem prefixed with marker.
            desired_stem = desired_out_path.stem
            src_stem = src_p.stem
            if desired_stem.startswith(src_stem):
                overrides["output_suffix"] = desired_stem[len(src_stem):]
            else:
                # Fallback: use the desired stem as-is; we'll rename afterwards.
                overrides["output_suffix"] = "_" + desired_stem
            out_ext = desired_out_path.suffix.lstrip(".").lower() or "png"
            # Normalize format aliases
            if out_ext == "jpeg":
                out_ext = "jpg"
            overrides["output_format"] = out_ext

            processor = self._build_processor_fn(tool_id, overrides)
            actual = processor.process_one(src_p, None)
            if actual is None:
                return False, "Processor returned None", None
            actual = Path(actual)
            if not actual.exists():
                return False, f"Processor reported output {actual} but file is missing", None
            return True, "", actual
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            print(f"[flow] Processor error on {tool_id}: {exc}\n{tb}")
            return False, str(exc), None

    # ------------------------------------------------------------------
    # Thread-safe signal emission helpers
    # ------------------------------------------------------------------

    def _emit_step_started(self, step_idx: int, total_steps: int, tool_id: str) -> None:
        QMetaObject.invokeMethod(
            self,
            "_on_step_started",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, step_idx),
            Q_ARG(int, total_steps),
            Q_ARG(str, tool_id),
        )

    def _emit_step_progress(self, step_idx: int, image_idx: int, pct: int) -> None:
        QMetaObject.invokeMethod(
            self,
            "_on_step_progress",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, step_idx),
            Q_ARG(int, image_idx),
            Q_ARG(int, pct),
        )

    def _emit_image_done(self, source_path: str, final_path: str, intermediates_json: str) -> None:
        QMetaObject.invokeMethod(
            self,
            "_on_image_done",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, source_path),
            Q_ARG(str, final_path),
            Q_ARG(str, intermediates_json),
        )

    def _emit_flow_finished(self, summary_json: str) -> None:
        QMetaObject.invokeMethod(
            self,
            "_on_flow_finished",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, summary_json),
        )

    def _emit_error(self, msg: str) -> None:
        QMetaObject.invokeMethod(
            self,
            "_on_flow_error",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, msg),
        )

    # ------------------------------------------------------------------
    # Slots (called via invokeMethod from the worker thread)
    # ------------------------------------------------------------------

    @Slot(int, int, str)
    def _on_step_started(self, step_idx: int, total_steps: int, tool_id: str) -> None:
        self.stepStarted.emit(step_idx, total_steps, tool_id)

    @Slot(int, int, int)
    def _on_step_progress(self, step_idx: int, image_idx: int, pct: int) -> None:
        self.stepProgress.emit(step_idx, image_idx, pct)

    @Slot(str, str, str)
    def _on_image_done(self, source_path: str, final_path: str, intermediates_json: str) -> None:
        self.imageDone.emit(source_path, final_path, intermediates_json)

    @Slot(str)
    def _on_flow_finished(self, summary_json: str) -> None:
        self.flowFinished.emit(summary_json)

    @Slot(str)
    def _on_flow_error(self, err_msg: str) -> None:
        self.flowError.emit(err_msg)
