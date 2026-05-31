"""
Output path planning for regular tool drops (central / TrialFlow mode).

Avoids duplicating central + tool folder segments when re-processing files
that already live under the tool output tree.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_LOG_LOCK = threading.Lock()
DEFAULT_ORIGINALS_FOLDER = "originals"


def default_log_path() -> Path:
    return Path(__file__).resolve().parent.parent / "tool_output_debug.log"


def safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def is_under(child: Path, parent: Path) -> bool:
    try:
        safe_resolve(child).relative_to(safe_resolve(parent))
        return True
    except ValueError:
        return False


def relative_safe(child: Path, parent: Path) -> Path:
    return safe_resolve(child).relative_to(safe_resolve(parent))


def normalize_central_path(value: Optional[str | Path]) -> Optional[Path]:
    """Return a resolved Path for a non-empty central output folder string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return safe_resolve(Path(text))


def effective_central_folder(
    *,
    source: Path,
    config_central: Optional[Path] = None,
    passed_central: Optional[Path] = None,
    allow_recovery: bool = True,
) -> Tuple[Optional[Path], Dict[str, Any]]:
    """
    Choose the central output root for tool-drop path planning.

    Tile jobs: prefer passed_central, then config_central. When recovery is
    allowed and the source already lives under the configured central folder
    but passed_central is empty, log a warning and use config_central.
    """
    config_res = normalize_central_path(config_central)
    passed_res = normalize_central_path(passed_central)
    source_res = safe_resolve(source)

    info: Dict[str, Any] = {
        "config_central_output_folder": str(config_res) if config_res else "",
        "passed_output_root": str(passed_res) if passed_res else "",
    }

    if not allow_recovery:
        effective = passed_res
        info["effective_output_root"] = str(effective) if effective else ""
        info["central_recovered"] = False
        return effective, info

    effective = passed_res or config_res
    recovered = False

    if config_res and is_under(source_res, config_res) and passed_res is None:
        if effective != config_res:
            effective = config_res
        recovered = True
        log_output_path_plan(
            event="CENTRAL_RECOVER",
            source_path=str(source_res),
            config_central_output_folder=str(config_res),
            passed_output_root="",
            message="source under configured central folder but passed output_root was empty",
        )

    if effective is None and config_res:
        effective = config_res

    info["effective_output_root"] = str(effective) if effective else ""
    info["central_recovered"] = recovered
    return effective, info


def log_output_path_plan(**fields: Any) -> None:
    from datetime import datetime

    parts = [f"{k}={v}" for k, v in fields.items()]
    message = "OUTPUT plan | " + " | ".join(parts)
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} | {message}\n"
    print(f"[tool-output] {message}")
    try:
        with _LOG_LOCK:
            path = default_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as exc:
        print(f"[tool-output] log write failed: {exc}")


def resolve_tool_output_dir(
    source: Path,
    tool_subfolder: str,
    central_folder: Optional[Path] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """
    Compute the directory where a processed file should be written.

    Returns (output_dir, debug_info).
    """
    source_res = safe_resolve(source)
    src_parent = source_res.parent
    tool_name = (tool_subfolder or "").strip()

    if central_folder is None or not str(central_folder).strip():
        subdir = src_parent / tool_name if tool_name else src_parent
        info = {
            "source_path": str(source_res),
            "output_root": "",
            "tool_output_root": str(subdir if tool_name else src_parent),
            "resolved_input_folder": str(src_parent),
            "resolved_originals_folder": "",
            "resolved_output_dir": str(subdir),
            "source_inside_tool_output_root": False,
            "mode": "next_to_source",
        }
        return subdir, info

    central = safe_resolve(Path(central_folder))
    tool_root = safe_resolve(central / tool_name) if tool_name else central
    originals_dir = tool_root / DEFAULT_ORIGINALS_FOLDER
    inside_tool = is_under(src_parent, tool_root)

    if inside_tool:
        rel = relative_safe(src_parent, tool_root)
        subdir = tool_root / rel if rel.parts else tool_root
        mode = "inside_tool_output"
    elif is_under(src_parent, central):
        rel = relative_safe(src_parent, central)
        subdir = tool_root / rel if rel.parts else tool_root
        mode = "inside_central_output"
    else:
        rel_parts = src_parent.parts[1:] if len(src_parent.parts) > 1 else ()
        subdir = tool_root.joinpath(*rel_parts) if rel_parts else tool_root
        mode = "mirror_external"

    info = {
        "source_path": str(source_res),
        "output_root": str(central),
        "tool_output_root": str(tool_root),
        "resolved_input_folder": str(src_parent),
        "resolved_originals_folder": str(originals_dir),
        "resolved_output_dir": str(subdir),
        "source_inside_tool_output_root": inside_tool,
        "mode": mode,
    }
    return subdir, info


def _path_is_occupied(path: Path, source_res: Path) -> bool:
    """True when path must not be used as output (source file or existing file)."""
    try:
        path_res = safe_resolve(path)
    except OSError:
        path_res = path
    if path_res == source_res:
        return True
    return path.exists()


def resolve_output_file(
    source: Path,
    tool_subfolder: str,
    suffix: str,
    out_ext: str,
    central_folder: Optional[Path] = None,
    skip_existing: bool = False,
    config_central_folder: Optional[Path] = None,
    allow_central_recovery: bool = True,
) -> Tuple[Path, Dict[str, Any]]:
    effective_central, central_info = effective_central_folder(
        source=source,
        config_central=config_central_folder if config_central_folder is not None else central_folder,
        passed_central=central_folder,
        allow_recovery=allow_central_recovery,
    )
    subdir, info = resolve_tool_output_dir(source, tool_subfolder, effective_central)
    info.update(central_info)
    source_res = safe_resolve(source)
    base = source.stem + suffix
    planned = subdir / f"{base}.{out_ext}"
    planned_exists = planned.exists() and safe_resolve(planned) != source_res

    info["planned_output_file"] = str(planned)
    info["planned_output_exists"] = planned_exists
    info["skip_existing_mode"] = bool(skip_existing)

    if skip_existing and planned_exists:
        info["final_output_file"] = str(planned)
        info["resolved_output_file"] = str(planned)
        info["skipped_due_to_existing"] = True
        log_output_path_plan(**info)
        return planned, info

    candidate = planned
    if _path_is_occupied(candidate, source_res):
        i = 2
        while _path_is_occupied(candidate, source_res):
            candidate = subdir / f"{base}-{i}.{out_ext}"
            i += 1
            if i > 9999:
                raise RuntimeError(f"Could not find unique output path for {source.name}")

    info["final_output_file"] = str(candidate)
    info["resolved_output_file"] = str(candidate)
    info["skipped_due_to_existing"] = False
    log_output_path_plan(**info)
    return candidate, info


def count_duplicate_segments(path: Path, segment: str) -> int:
    """Count how many times a path part appears (case-insensitive on Windows)."""
    target = segment.lower()
    return sum(1 for p in path.parts if p.lower() == target)
