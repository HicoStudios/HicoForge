# HicoForge v1.1.0 — Flow Tiles: Build Notes

## Files

| File | Purpose |
|------|---------|
| `core/flow_engine.py` | `Flow`, `FlowStep`, `FlowEngine(build_processor_fn, parent)` |
| `core/flow_store.py` | Config persistence — list/get/save/delete/export/import flows |
| `app/flow_tile.py` | Widget — chain icon, accent border, progress bar, drag-drop, menus |
| `app/flow_builder_dialog.py` | Flow builder + tool picker + flow-picker dialogs |
| `app/flow_run_dialog.py` | Per-image vs stage-by-stage mode picker |
| `app/flow_cull_dialog.py` | Post-run thumbnail review — star/trash/promote |

---

## Wiring Contract — MainWindow integration

The engine is decoupled from MainWindow via a single callback:

```python
build_processor_fn: Callable[[tool_id: str, overrides: dict], BaseProcessor]
```

The host (MainWindow) supplies an adapter that wraps the existing
`processors.factory.build_processor`. Suggested implementation, modeled on
the existing `_build_processor_for_tool` (main_window.py:681):

```python
def _build_flow_processor(self, tool_id: str, overrides: dict):
    from processors.tool_registry import get_tool
    from processors.factory import build_processor

    tool = get_tool(tool_id)
    if tool is None:
        raise ValueError(f"Unknown tool_id: {tool_id}")

    models_folder = Path(self.cfg.get("models_folder", ""))
    central_str = (self.cfg.get("central_output_folder") or "").strip()
    central = Path(central_str) if central_str else None

    # Merge tile defaults (if you store any) with the flow's per-step overrides.
    # Flow's overrides win over global tile_settings since the user set them per-step.
    merged = {}
    merged.update(self.cfg.get("flow_default_tile_settings", {}))
    merged.update(overrides or {})

    return build_processor(
        tool, models_folder, self.model_cache, self.gpu,
        overrides=merged,
        central_folder=central,
    )
```

Then pass it when constructing FlowTile widgets:

```python
tile = FlowTile(
    slot_key="row0_col2",
    build_processor_fn=self._build_flow_processor,
    parent=grid_container,
)
```

The engine sets `output_suffix` and `output_format` overrides per step so each
intermediate is identifiable; it then moves the processor's output to a
canonical path: `{output_dir}/{basename}_step{NN}_{tool_id}.{ext}` and finally
`{output_dir}/{basename}_final.{ext}`.

---

## Stubs / Wiring TODOs (intentional — patch script handles)

### 1. Per-tool settings dialog (HIGH)
`app/flow_builder_dialog.py` → `StepRowWidget._on_edit_step_settings()`.
Replace placeholder QMessageBox with whatever existing dialog opens the per-tool
settings (the same one used by ToolPickerDialog). On accept, write returned
dict into `self._step.settings_override`.

### 2. `edit_before_run` runtime resolution (MEDIUM)
Engine itself does NOT open dialogs. Caller (FlowTile or the patch's wrapper)
must iterate `flow.steps`, open the per-tool settings dialog for each step
where `step.edit_before_run is True`, collect the dict, and pass them as
`resolved_settings={step_idx: settings_dict}` into `engine.run_flow()`.

### 3. `theme.FLOW_ACCENT` constant (LOW)
All app files fall back to `theme.EMBER_ORANGE` if `theme.FLOW_ACCENT` is
absent. Add `FLOW_ACCENT = "#yourhex"` to `app/theme.py` if you want a
distinct color.

### 4. Slot persistence (HIGH)
Patch script should:
- On startup, read `cfg["flow_tile_slots"][slot_key]` and call
  `flow_tile.assign_flow(flow_id)`.
- Connect `flowAssigned` / `slotCleared` signals to a save handler that
  updates `cfg["flow_tile_slots"]` and persists.

### 5. "New Flow Tile" placement (MEDIUM)
Add a menu item or empty-slot context option that creates a `FlowTile` in a
chosen grid cell. The patch script can replace a regular `Tile` instance with
a `FlowTile` based on the saved binding.

---

## Verified Real APIs (sourced from extracted v1.0.0)

| Symbol | Real signature / shape | File |
|--------|------------------------|------|
| `ALL_TOOLS` | `list[ToolDef]` (NOT dict) | `processors/tool_registry.py:320` |
| `ToolDef` | dataclass: id, name, category, description, glyph, processor_key, model_filename, default_settings, default_suffix, default_format, default_output_scale, native_scale, ... | `processors/tool_registry.py:33` |
| `get_tool(id)` | `Optional[ToolDef]` | `processors/tool_registry.py:327` |
| `tools_by_category()` | `dict[str, list[ToolDef]]` | `processors/tool_registry.py:334` |
| `CATEGORY_ORDER` | `list[str]` | `processors/tool_registry.py:23` |
| `build_processor(tool, models_folder, model_cache, gpu, overrides=None, central_folder=None)` | Returns `BaseProcessor`. Lives in `processors.factory` (NOT `core`). | `processors/factory.py:34` |
| `BaseProcessor.process_one(source: Path, progress: Optional[Callable]) -> Path` | Processor decides output path via `ctx.output_subfolder` + `ctx.output_suffix` + `ctx.output_format` + `ctx.central_folder`. Returns actual output path. | `processors/base.py:44` |
| `ProcessorContext` overrides honored | `target_format`/`output_format`, `jpg_quality`, `webp_quality`, `output_scale`, `output_suffix`, `tile_size`, `preserve_alpha`, `target`, `custom_dim`, `allow_upscale`, `rembg_model` | `processors/factory.py:50-58` |
| `ToastManager` | `MainWindow.toasts.show_toast(message, kind="info"\|"success"\|"error")`. NO `.instance()` accessor. | `app/main_window.py:153`, `app/toast.py:131` |
| `MainWindow._build_processor_for_tool(tool_id, slot_index)` | Existing pattern that the JobQueue uses. Mirror this for FlowEngine. | `app/main_window.py:681` |
| `theme.EMBER_ORANGE` | Hex string | `app/theme.py` |

---

## Test Order

1. `core/flow_store.py` — unit-test with a throwaway config dict.
2. `core/flow_engine.py` — supply a fake `build_processor_fn` returning a dummy
   processor whose `.process_one(src, progress)` calls `shutil.copy(src, out)`.
   Verify per_image and per_stage produce correct `_stepNN_` files and `_final`.
3. `app/flow_builder_dialog.py` — launch standalone, add steps, save.
4. `app/flow_run_dialog.py` — launch with a fake Flow, 3 image paths.
5. `app/flow_tile.py` — embed, assign a flow, drag-drop 1 then 2 images.
6. `app/flow_cull_dialog.py` — launch with synthetic summary dict.
7. End-to-end — patch into live MainWindow grid, 3-step flow (Resize → Convert
   → DitherDeleter), drop 2 images, stage-by-stage mode, cull results.
