"""
Structured and flat run output paths for fixed Flow tiles.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.flow_engine import Flow, FlowStep

OUTPUT_MODE_HICO_PROCESSED = "hico_processed"
OUTPUT_MODE_IN_SOURCE = "in_source"
OUTPUT_MODE_IN_SOURCE_ALIAS = "in_source_folder"
OUTPUT_MODE_CUSTOM = "custom_folder"


def normalize_output_mode(mode: str) -> str:
    m = (mode or "").strip().lower()
    if m in (OUTPUT_MODE_IN_SOURCE, OUTPUT_MODE_IN_SOURCE_ALIAS, "in_source_folder"):
        return OUTPUT_MODE_IN_SOURCE
    if m == OUTPUT_MODE_CUSTOM:
        return OUTPUT_MODE_CUSTOM
    return OUTPUT_MODE_HICO_PROCESSED


def is_in_source_mode(tile_cfg: Dict[str, Any]) -> bool:
    return normalize_output_mode(str(tile_cfg.get("output_mode") or "")) == OUTPUT_MODE_IN_SOURCE

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]+')
_HICOFORGE_OUTPUT_SUFFIX = re.compile(
    r"^(?P<base>.+?)__r(?P<run>\d{3})__(?P<step>final|step\d{2}_[^_]+|run_manifest)(?:__v\d+)?$",
    re.IGNORECASE,
)
_RUN_ID_IN_NAME = re.compile(r"__r(\d{3})__", re.IGNORECASE)


def safe_folder_name(name: str, fallback: str = "Flow") -> str:
    cleaned = _INVALID_CHARS.sub("_", (name or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned or fallback


def safe_filename(stem: str, ext: str, fallback: str = "output") -> str:
    stem = safe_folder_name(stem, fallback)
    ext = ext if ext.startswith(".") else f".{ext}"
    if ext.lower() == ".jpeg":
        ext = ".jpg"
    return f"{stem}{ext}"


def step_folder_name(step_idx: int, step: FlowStep) -> str:
    safe_tool = safe_folder_name(step.tool_id, "step")
    return f"step_{step_idx + 1:02d}_{safe_tool}"


def step_token_for_filename(step_idx: int, step: FlowStep, is_final: bool = False) -> str:
    if is_final:
        return "final"
    safe_tool = safe_folder_name(step.tool_id, "step")
    return f"step{step_idx + 1:02d}_{safe_tool}"


def default_output_root(install_root: Path) -> Path:
    return install_root / "Processed"


def _run_num_from_id(run_id: str) -> str:
    if run_id.startswith("Run_"):
        return run_id.split("_", 1)[1]
    if run_id.startswith("r"):
        return run_id[1:]
    return run_id


def expand_filename_pattern(
    pattern: str,
    *,
    source_path: Path,
    base_name_override: str,
    flow_name: str,
    step_name: str,
    run_id: str,
    image_index: int,
    is_final: bool = False,
    source_name: Optional[str] = None,
) -> str:
    now = datetime.now()
    source_stem = source_name if source_name is not None else source_path.stem
    base_name = (base_name_override or "").strip() or source_stem
    if is_final:
        step_token = "final"
    else:
        step_token = safe_folder_name(step_name, "step")
    tokens = {
        "source_name": source_stem,
        "base_name": base_name,
        "flow_name": safe_folder_name(flow_name, "Flow"),
        "step_name": step_token,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H%M"),
        "run_id": _run_num_from_id(run_id),
        "index": f"{image_index:02d}",
        "final": "final",
    }
    out = pattern or "{source_name}__r{run_id}__{step_name}"
    for key, val in tokens.items():
        out = out.replace("{" + key + "}", val)
    out = _INVALID_CHARS.sub("_", out)
    out = out.strip(" ._") or f"{source_stem}_out"
    return out


def strip_hicoforge_suffix(stem: str) -> str:
    """Strip trailing HicoForge flat-output tokens to recover the original source stem."""
    current = (stem or "").strip()
    if not current:
        return stem
    while True:
        m = _HICOFORGE_OUTPUT_SUFFIX.match(current)
        if not m:
            break
        current = m.group("base")
    return current or stem


def derive_source_name(source_path: Path, base_name_override: str = "") -> str:
    override = (base_name_override or "").strip()
    if override:
        return safe_folder_name(override, "source")
    return safe_folder_name(strip_hicoforge_suffix(source_path.stem), source_path.stem)


def sanitize_filename(stem: str, ext: str, fallback: str = "output") -> str:
    return safe_filename(stem, ext, fallback)


def make_unique_path(path: Path, reserved: Optional[set] = None) -> Path:
    """Return a non-existing path; append __v2, __v3, ... when the target already exists."""
    reserved = reserved or set()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    if not path.exists() and resolved not in reserved:
        return path

    stem = path.stem
    ext = path.suffix
    parent = path.parent
    base_stem = re.sub(r"__v\d+$", "", stem, flags=re.IGNORECASE)
    n = 2
    while n < 10000:
        candidate = parent / f"{base_stem}__v{n}{ext}"
        try:
            c_resolved = candidate.resolve()
        except OSError:
            c_resolved = candidate
        if not candidate.exists() and c_resolved not in reserved:
            return candidate
        n += 1
    raise RuntimeError(f"Could not find unique path for {path}")


def unique_path(path: Path) -> Path:
    """Backward-compatible alias for make_unique_path."""
    return make_unique_path(path)


def _max_run_num_in_folder(folder: Path, source_name: Optional[str] = None) -> int:
    max_n = 0
    if not folder.is_dir():
        return 0

    if source_name:
        safe = re.escape(safe_folder_name(source_name, "source"))
        file_pat = re.compile(
            rf"^{safe}__r(\d{{3}})__(?:final|step\d{{2}}_|run_manifest)",
            re.IGNORECASE,
        )
    else:
        file_pat = None

    for child in folder.iterdir():
        if not child.is_file():
            continue
        if child.name.startswith("HicoForge_Flow_Run_") and child.name.endswith("_manifest.json"):
            try:
                part = child.name.replace("HicoForge_Flow_Run_", "").replace("_manifest.json", "")
                max_n = max(max_n, int(part))
            except ValueError:
                pass
            continue
        if file_pat:
            m = file_pat.match(child.stem)
            if m:
                max_n = max(max_n, int(m.group(1)))
                continue
        for m in _RUN_ID_IN_NAME.finditer(child.name):
            try:
                max_n = max(max_n, int(m.group(1)))
            except ValueError:
                pass
    return max_n


def next_run_id_for_source_folder(folder: Path, source_name: str) -> str:
    """Next run id for a single source base name within a folder."""
    max_n = _max_run_num_in_folder(folder, source_name=source_name)
    return f"r{max_n + 1:03d}"


def next_run_id_for_batch_folder(folder: Path) -> str:
    """Next run id for a multi-image batch in one folder."""
    max_n = _max_run_num_in_folder(folder, source_name=None)
    return f"r{max_n + 1:03d}"


def resolve_output_root(tile_cfg: Dict[str, Any], install_root: Optional[Path] = None) -> Path:
    """Return the configured output root for Processed / Custom modes."""
    mode = normalize_output_mode(str(tile_cfg.get("output_mode") or ""))
    if mode == OUTPUT_MODE_CUSTOM:
        return Path(str(tile_cfg.get("custom_output_folder") or ""))
    root = Path(str(tile_cfg.get("output_root") or ""))
    if not str(tile_cfg.get("output_root") or "").strip():
        if install_root is None:
            install_root = Path(__file__).resolve().parent.parent
        return default_output_root(install_root)
    return root


def resolve_project_folder_name(tile_cfg: Dict[str, Any]) -> str:
    """Persistent project/character folder name (never display_name)."""
    raw = str(tile_cfg.get("flow_folder_name") or "").strip()
    if not raw:
        tile_id = str(tile_cfg.get("tile_id") or "flow_1")
        raw = f"Flow_{tile_id.rsplit('_', 1)[-1]}"
    return safe_folder_name(raw, "Flow")


def resolve_project_folder(output_root: Path, flow_folder_name: str) -> Path:
    return output_root / resolve_project_folder_name({"flow_folder_name": flow_folder_name})


def next_run_number(project_folder: Path) -> int:
    """Scan existing Run_### folders and return the next run number."""
    max_n = 0
    if project_folder.is_dir():
        for child in project_folder.iterdir():
            if child.is_dir() and child.name.startswith("Run_"):
                try:
                    max_n = max(max_n, int(child.name.split("_", 1)[1]))
                except (IndexError, ValueError):
                    continue
    return max_n + 1


def log_resolved_output_paths(
    *,
    display_name: str,
    flow_folder_name: str,
    base_name_override: str,
    resolved_output_root: str,
    resolved_project_folder: str,
    resolved_run_folder: str,
    output_mode: str = "",
    run_id: str = "",
) -> None:
    """Print and append output path resolution to flow_vram_debug.log."""
    parts = [
        "OUTPUT paths",
        f"display_name={display_name}",
        f"flow_folder_name={flow_folder_name}",
        f"base_name_override={base_name_override or '(none)'}",
        f"resolved_output_root={resolved_output_root}",
        f"resolved_project_folder={resolved_project_folder}",
        f"resolved_run_folder={resolved_run_folder}",
    ]
    if output_mode:
        parts.append(f"output_mode={output_mode}")
    if run_id:
        parts.append(f"run_id={run_id}")
    message = " | ".join(parts)
    print(f"[flow-paths] {message}")
    try:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} | {message}\n"
        log_path = default_unified_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:
        print(f"[flow-paths] log write failed: {exc}")


def allocate_run_dir(output_root: Path, flow_folder_name: str) -> tuple[Path, str]:
    project_folder = resolve_project_folder(output_root, flow_folder_name)
    project_folder.mkdir(parents=True, exist_ok=True)
    run_num = next_run_number(project_folder)
    run_id = f"Run_{run_num:03d}"
    run_dir = project_folder / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir, run_id


def allocate_in_source_run_id(folder: Path, source_name: Optional[str] = None) -> str:
    if source_name:
        return next_run_id_for_source_folder(folder, source_name)
    return next_run_id_for_batch_folder(folder)


@dataclass
class StructuredRunContext:
    tile_id: str
    flow_id: str
    display_name: str
    flow_name: str
    output_mode: str
    output_root: str
    flow_folder_name: str
    base_name_override: str
    filename_pattern: str
    run_id: str
    run_dir: Path
    project_folder: Path
    originals_dir: Optional[Path]
    final_dir: Optional[Path]
    step_dir_names: List[str]
    step_dirs: List[Path]
    manifest_path: Path
    started_at: str
    manifest: Dict[str, Any] = field(default_factory=dict)
    flat_output_dir: Optional[Path] = None
    _reserved_paths: set = field(default_factory=set, repr=False)

    def _allocate_output_path(
        self,
        folder: Path,
        stem: str,
        ext: str,
        source_path: Path,
    ) -> Path:
        candidate = folder / safe_filename(stem, ext)
        avoid: set = set(self._reserved_paths)
        try:
            avoid.add(source_path.resolve())
        except OSError:
            avoid.add(source_path)
        path = make_unique_path(candidate, reserved=avoid)
        try:
            self._reserved_paths.add(path.resolve())
        except OSError:
            self._reserved_paths.add(path)
        return path

    def write_manifest(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh, indent=2, ensure_ascii=False)

    def path_for_output(
        self,
        source_path: Path,
        step_idx: int,
        step: FlowStep,
        image_index: int,
        ext: str,
        is_final: bool = False,
    ) -> Path:
        clean_source = derive_source_name(source_path, self.base_name_override)
        if self.output_mode == OUTPUT_MODE_IN_SOURCE:
            step_label = step_token_for_filename(step_idx, step, is_final=is_final)
        else:
            step_label = "final" if is_final else step.effective_label()
        stem = expand_filename_pattern(
            self.filename_pattern,
            source_path=source_path,
            base_name_override=self.base_name_override,
            flow_name=self.flow_folder_name,
            step_name=step_label,
            run_id=self.run_id,
            image_index=image_index,
            is_final=is_final,
            source_name=clean_source,
        )
        if self.output_mode == OUTPUT_MODE_IN_SOURCE:
            folder = source_path.parent
            return self._allocate_output_path(folder, stem, ext, source_path)
        if is_final and self.final_dir is not None:
            return self._allocate_output_path(self.final_dir, stem, ext, source_path)
        if step_idx < len(self.step_dirs):
            return self._allocate_output_path(self.step_dirs[step_idx], stem, ext, source_path)
        return self._allocate_output_path(self.run_dir, stem, ext, source_path)


def create_run_context(
    flow: Flow,
    tile_cfg: Dict[str, Any],
    install_root: Optional[Path] = None,
) -> StructuredRunContext:
    mode = normalize_output_mode(str(tile_cfg.get("output_mode") or ""))
    pattern = str(tile_cfg.get("filename_pattern") or "{source_name}__r{run_id}__{step_name}")
    base_override = str(tile_cfg.get("base_name_override") or "")
    display_name = str(tile_cfg.get("display_name") or flow.name)
    flow_folder = resolve_project_folder_name(tile_cfg)
    started = datetime.now().isoformat()

    output_root = resolve_output_root(tile_cfg, install_root)
    project_folder = output_root / flow_folder
    run_dir, run_id = allocate_run_dir(output_root, flow_folder)

    step_names = [step_folder_name(i, s) for i, s in enumerate(flow.steps)]
    step_dirs: List[Path] = []
    for name in step_names:
        d = run_dir / name
        d.mkdir(parents=True, exist_ok=True)
        step_dirs.append(d)
    originals_dir = run_dir / "originals"
    final_dir = run_dir / "final"
    originals_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    log_resolved_output_paths(
        display_name=display_name,
        flow_folder_name=flow_folder,
        base_name_override=base_override,
        resolved_output_root=str(output_root),
        resolved_project_folder=str(project_folder),
        resolved_run_folder=str(run_dir),
        output_mode=mode,
        run_id=run_id,
    )

    manifest = _base_manifest(tile_cfg, flow, mode, str(output_root), started, display_name)
    manifest["run_folder"] = str(run_dir)
    manifest["run_id"] = run_id
    manifest["project_folder"] = str(project_folder)
    manifest["output_context"] = "multi_step_flow"

    log_unified_output_event(
        output_context="multi_step_flow",
        global_output_root=str(output_root),
        project_folder_name=flow_folder,
        resolved_run_folder=str(run_dir),
        run_id=run_id,
    )

    ctx = StructuredRunContext(
        tile_id=str(tile_cfg.get("tile_id") or ""),
        flow_id=flow.id,
        display_name=display_name,
        flow_name=display_name,
        output_mode=mode,
        output_root=str(output_root),
        flow_folder_name=flow_folder,
        base_name_override=base_override,
        filename_pattern=pattern,
        run_id=run_id,
        run_dir=run_dir,
        project_folder=project_folder,
        originals_dir=originals_dir,
        final_dir=final_dir,
        step_dir_names=step_names,
        step_dirs=step_dirs,
        manifest_path=run_dir / "run_manifest.json",
        started_at=started,
        manifest=manifest,
    )
    ctx.write_manifest()
    return ctx


def prepare_in_source_run(
    flow: Flow,
    tile_cfg: Dict[str, Any],
    source_paths: List[str],
) -> StructuredRunContext:
    """Flat outputs in each source file's parent folder. No subfolders created."""
    paths = [Path(p) for p in source_paths]
    first = paths[0]
    output_dir = first.parent
    is_batch = len(paths) > 1

    pattern = str(tile_cfg.get("filename_pattern") or "{source_name}__r{run_id}__{step_name}")
    base_override = str(tile_cfg.get("base_name_override") or "")
    display_name = str(tile_cfg.get("display_name") or flow.name)
    flow_folder = resolve_project_folder_name(tile_cfg)
    started = datetime.now().isoformat()

    run_id = (
        next_run_id_for_batch_folder(output_dir)
        if is_batch
        else next_run_id_for_source_folder(
            output_dir,
            derive_source_name(first, base_override),
        )
    )
    run_num = _run_num_from_id(run_id)
    clean_source = derive_source_name(first, base_override)

    log_resolved_output_paths(
        display_name=display_name,
        flow_folder_name=flow_folder,
        base_name_override=base_override,
        resolved_output_root=str(output_dir),
        resolved_project_folder=str(output_dir),
        resolved_run_folder=str(output_dir),
        output_mode=OUTPUT_MODE_IN_SOURCE,
        run_id=run_id,
    )

    if is_batch:
        manifest_path = make_unique_path(
            output_dir / f"HicoForge_Flow_Run_{run_num}_manifest.json"
        )
    else:
        manifest_stem = f"{clean_source}__r{run_num}__run_manifest"
        manifest_path = make_unique_path(output_dir / safe_filename(manifest_stem, ".json"))

    manifest = _base_manifest(tile_cfg, flow, OUTPUT_MODE_IN_SOURCE, str(output_dir), started, display_name)
    manifest["run_id"] = run_id
    manifest["run_folder"] = str(output_dir)
    manifest["output_mode"] = OUTPUT_MODE_IN_SOURCE
    manifest["creates_subfolders"] = False

    ctx = StructuredRunContext(
        tile_id=str(tile_cfg.get("tile_id") or ""),
        flow_id=flow.id,
        display_name=display_name,
        flow_name=display_name,
        output_mode=OUTPUT_MODE_IN_SOURCE,
        output_root=str(output_dir),
        flow_folder_name=flow_folder,
        base_name_override=base_override,
        filename_pattern=pattern,
        run_id=run_id,
        run_dir=output_dir,
        project_folder=output_dir,
        originals_dir=None,
        final_dir=None,
        step_dir_names=[],
        step_dirs=[],
        manifest_path=manifest_path,
        started_at=started,
        manifest=manifest,
        flat_output_dir=output_dir,
    )
    ctx.write_manifest()
    return ctx


# Backward-compatible alias
def prepare_in_source_batch(flow: Flow, tile_cfg: Dict[str, Any], source_paths: List[str]) -> StructuredRunContext:
    return prepare_in_source_run(flow, tile_cfg, source_paths)


def _base_manifest(
    tile_cfg: Dict[str, Any],
    flow: Flow,
    mode: str,
    output_root: str,
    started: str,
    display_name: str,
) -> Dict[str, Any]:
    return {
        "run_id": "",
        "flow_tile_id": str(tile_cfg.get("tile_id") or ""),
        "flow_id": flow.id,
        "display_name": display_name,
        "flow_name": display_name,
        "flow_folder_name": resolve_project_folder_name(tile_cfg),
        "output_mode": mode,
        "output_root": output_root,
        "custom_output_folder": str(tile_cfg.get("custom_output_folder") or ""),
        "base_name_override": str(tile_cfg.get("base_name_override") or ""),
        "filename_pattern": str(tile_cfg.get("filename_pattern") or "{source_name}__r{run_id}__{step_name}"),
        "project_folder": "",
        "run_folder": "",
        "step_names": [step_folder_name(i, s) for i, s in enumerate(flow.steps)],
        "source_files": [],
        "started_at": started,
        "ended_at": "",
        "images": [],
    }


def copy_original(source_path: Path, originals_dir: Path) -> Path:
    dest = make_unique_path(originals_dir / source_path.name)
    if source_path.resolve() != dest.resolve():
        shutil.copy2(source_path, dest)
    return dest


def finalize_manifest(ctx: StructuredRunContext, image_results: List[Dict[str, Any]]) -> None:
    ctx.manifest["images"] = image_results
    ctx.manifest["ended_at"] = datetime.now().isoformat()
    ctx.manifest["run_id"] = ctx.run_id
    ctx.manifest["run_folder"] = str(ctx.run_dir)
    ctx.manifest["project_folder"] = str(ctx.project_folder)
    ctx.write_manifest()


def default_unified_log_path() -> Path:
    from core.tool_output_paths import default_log_path
    return default_log_path()


def log_unified_output_event(**fields: Any) -> None:
    """Structured output log (tile-as-flow and multi-step flow)."""
    from core.tool_output_paths import log_output_path_plan
    log_output_path_plan(**fields)


def create_single_tool_run_context(
    tool_id: str,
    source_paths: List[Path],
    tile_cfg: Dict[str, Any],
    install_root: Optional[Path] = None,
) -> tuple[StructuredRunContext, Flow]:
    """
    Allocate Run_### for a standalone tile drop (one-step flow).
    """
    from processors.tool_registry import get_tool

    paths = [Path(p) for p in source_paths]
    tool = get_tool(tool_id)
    label = tool.name if tool else tool_id
    step = FlowStep(tool_id=tool_id, label=label)
    flow = Flow(id=f"single_tool_{tool_id}", name=label, steps=[step])

    cfg = dict(tile_cfg)
    cfg.setdefault("display_name", label)

    if is_in_source_mode(cfg):
        ctx = prepare_in_source_run(flow, cfg, [str(p) for p in paths])
    else:
        ctx = create_run_context(flow, cfg, install_root)
        if ctx.originals_dir is not None:
            for src in paths:
                try:
                    copy_original(src, ctx.originals_dir)
                except Exception as exc:
                    print(f"[output] copy original failed for {src}: {exc}")

    ctx.manifest["output_context"] = "single_tile_as_flow"
    ctx.manifest["single_tool_id"] = tool_id
    ctx.write_manifest()

    log_unified_output_event(
        output_context="single_tile_as_flow",
        tool_id=tool_id,
        global_output_root=str(ctx.output_root),
        project_folder_name=ctx.flow_folder_name,
        resolved_run_folder=str(ctx.run_dir),
        step_output_folder=str(ctx.step_dirs[0]) if ctx.step_dirs else "",
    )
    return ctx, flow


def append_manifest_image(ctx: StructuredRunContext, entry: Dict[str, Any]) -> None:
    images = ctx.manifest.setdefault("images", [])
    if not isinstance(images, list):
        images = []
        ctx.manifest["images"] = images
    images.append(entry)
    ctx.write_manifest()


# Backward-compatible alias
def create_structured_run(
    flow: Flow,
    tile_id: str,
    output_root: Path,
    flow_folder_name: str,
) -> StructuredRunContext:
    tile_cfg = {
        "tile_id": tile_id,
        "output_mode": OUTPUT_MODE_HICO_PROCESSED,
        "output_root": str(output_root),
        "flow_folder_name": flow_folder_name,
        "display_name": flow.name,
        "base_name_override": "",
        "filename_pattern": "{source_name}__r{run_id}__{step_name}",
    }
    return create_run_context(flow, tile_cfg)
