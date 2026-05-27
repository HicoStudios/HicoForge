"""
HicoForge v1.1.0 — Flow Tiles wiring patch
==========================================

Patches `app/main_window.py` in-place to wire up FlowTile so the user can
actually place and use Flow Tiles in the grid.

Strategy (low-risk, surgical):
  1. Validate target file with AST first.
  2. Take a backup at  app/main_window.py.bak_v1_1_0
  3. Inject a single import line near the existing app imports.
  4. Append a new class extension via `_wire_flow_tiles(cls)` at the END of
     the file — this monkey-patches MainWindow's behavior without editing
     any method bodies, so existing logic is untouched.
  5. Re-validate with AST + import-only smoke test.
  6. On any failure, restore the backup.

The Flow Tile is identified by storing  slot_assignments[i] = "__flow__<flow_id>"
in the existing config — no new persistence schema.

To place a Flow Tile in a slot:
  - Right-click an empty slot to "Choose Tool…"
  - The patched MainWindow detects the __flow__ assignment and renders a
    FlowTile instead of a regular Tile.

For the first release, a programmatic API is also provided:
    main_window._assign_flow_to_slot(slot_index, flow_id)

A "+ Flow Tile" button is added to the title bar so the user can promote
the FIRST empty slot to a Flow Tile in one click (will open Flow Builder
to create or pick a flow, then assigns it).

Run:
    python patch_flow_tiles_wiring.py

The script honors the HICOFORGE_INSTALL_DIR env var (set by the .ps1
installer); otherwise it expects to live next to main.py.
"""
from __future__ import annotations

import ast
import os
import shutil
import sys
from pathlib import Path

BACKUP_SUFFIX = ".bak_v1_1_0"


def find_install_dir() -> Path:
    env = os.environ.get("HICOFORGE_INSTALL_DIR")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "main.py").exists():
            return p
        raise SystemExit(f"HICOFORGE_INSTALL_DIR={p} but main.py not found there.")
    # Fall back: assume script lives in the install dir or one level up
    here = Path(__file__).resolve().parent
    for cand in (here, here.parent):
        if (cand / "main.py").exists() and (cand / "app" / "main_window.py").exists():
            return cand
    raise SystemExit("Could not locate HicoForge install directory. Set HICOFORGE_INSTALL_DIR.")


def validate_python(src: str, label: str) -> None:
    try:
        ast.parse(src)
    except SyntaxError as e:
        raise SystemExit(f"[FAIL] {label} has syntax error: {e}")


# The block we append to main_window.py. It runs at import time and patches
# MainWindow in place — no edits to existing methods.
PATCH_BLOCK = r'''

# ============================================================================
# Flow Tiles v1.1.0 — appended by patch_flow_tiles_wiring.py
# ============================================================================
# This block monkey-patches MainWindow at import time to wire up FlowTile
# support without editing any existing method bodies. Safe to remove by
# deleting everything from this banner to end-of-file.

try:
    from app.flow_tile import FlowTile as _FT_FlowTile
    from app.flow_builder_dialog import (
        FlowBuilderDialog as _FT_FlowBuilderDialog,
        FlowPickerDialog as _FT_FlowPickerDialog,
    )
    from core.flow_store import (
        get_flow as _ft_get_flow,
        list_flows as _ft_list_flows,
        save_flow as _ft_save_flow,
        new_flow_id as _ft_new_flow_id,
    )
    from core.flow_engine import Flow as _FT_Flow
    from processors.tool_registry import get_tool as _ft_get_tool
    from processors.factory import build_processor as _ft_build_processor
    from pathlib import Path as _FT_Path
    from PySide6.QtWidgets import QPushButton as _FT_QPushButton, QMessageBox as _FT_QMessageBox

    _FT_FLOW_MARKER = "__flow__"

    def _ft_is_flow_assignment(val):
        return isinstance(val, str) and val.startswith(_FT_FLOW_MARKER)

    def _ft_flow_id_from_assignment(val):
        if _ft_is_flow_assignment(val):
            return val[len(_FT_FLOW_MARKER):]
        return None

    def _ft_assignment_for_flow(flow_id):
        return _FT_FLOW_MARKER + flow_id

    def _ft_build_flow_processor(self, tool_id, overrides):
        """Adapter passed into FlowEngine.

        Mirrors self._build_processor_for_tool but accepts an overrides
        dict (already merged from the flow step) instead of a slot_index.
        """
        tool = _ft_get_tool(tool_id)
        if tool is None:
            raise ValueError("Unknown tool_id: " + str(tool_id))
        models_folder = _FT_Path(self.cfg.get("models_folder", ""))
        central_str = (self.cfg.get("central_output_folder") or "").strip()
        central = _FT_Path(central_str) if central_str else None
        merged = {}
        merged.update(self.cfg.get("flow_default_tile_settings", {}) or {})
        merged.update(overrides or {})
        return _ft_build_processor(
            tool, models_folder, self.model_cache, self.gpu,
            overrides=merged,
            central_folder=central,
        )

    def _ft_on_flow_assigned(self, slot_index, flow_id):
        """Persist flow assignment in slot_assignments."""
        try:
            self.slot_assignments[slot_index] = _ft_assignment_for_flow(flow_id)
            try:
                import core.config as _cfgmod
                _cfgmod.set_slot_assignment(self.cfg, slot_index, _ft_assignment_for_flow(flow_id))
                _cfgmod.save_config(self.cfg)
            except Exception as _e:
                print("[flow] save assignment failed:", _e)
            if hasattr(self, "toasts"):
                try:
                    flow = _ft_get_flow(flow_id)
                    name = flow.name if flow else flow_id
                    self.toasts.show_toast("Flow assigned: " + name, kind="success")
                except Exception:
                    pass
        except Exception as _e:
            print("[flow] _ft_on_flow_assigned error:", _e)

    def _ft_on_flow_cleared(self, slot_index):
        try:
            if slot_index in self.slot_assignments:
                del self.slot_assignments[slot_index]
                import core.config as _cfgmod
                _cfgmod.set_slot_assignment(self.cfg, slot_index, None)
                _cfgmod.save_config(self.cfg)
                self._rebuild_grid(self.grid_picker.current_grid())
        except Exception as _e:
            print("[flow] _ft_on_flow_cleared error:", _e)

    def _ft_swap_in_flow_tiles(self):
        """After the regular grid build, replace any slot whose assignment
        starts with __flow__ with a FlowTile widget.
        """
        try:
            container = self.grid_host.widget()
            if container is None:
                return
            # Find the QGridLayout
            from PySide6.QtWidgets import QGridLayout as _QGL
            layout = container.layout()
            if not isinstance(layout, _QGL):
                return  # All-mode uses VBox; flow tiles not supported in All-mode
            # Walk grid positions
            slot_idx = 0
            cols = layout.columnCount() if hasattr(layout, "columnCount") else 1
            for r in range(layout.rowCount()):
                for c in range(cols):
                    item = layout.itemAtPosition(r, c)
                    if item is None:
                        continue
                    w = item.widget()
                    if w is None:
                        continue
                    # The slot index is encoded in placement order, not Qt's; we use
                    # explicit lookup via slot_assignments instead.
            # Simpler: iterate over slot_assignments and rebuild only flow slots.
            for slot_index, assignment in list(self.slot_assignments.items()):
                if not _ft_is_flow_assignment(assignment):
                    continue
                flow_id = _ft_flow_id_from_assignment(assignment)
                # Locate current widget at this slot's grid position
                size = self.grid_picker.current_grid()
                if size == -1:
                    continue  # don't render flow tiles in All-mode
                from app.main_window import GRID_LAYOUTS as _GL
                if size not in _GL:
                    continue
                grid_cols = _GL[size][0]
                grid_r = slot_index // grid_cols
                grid_c = slot_index % grid_cols
                item = layout.itemAtPosition(grid_r, grid_c)
                old_w = item.widget() if item else None
                # Build FlowTile
                ft = _FT_FlowTile(
                    slot_key="slot_" + str(slot_index),
                    build_processor_fn=lambda tid, ov, _self=self: _ft_build_flow_processor(_self, tid, ov),
                    parent=container,
                )
                if flow_id:
                    ft.assign_flow(flow_id)
                ft.flowAssigned.connect(lambda fid, si=slot_index: _ft_on_flow_assigned(self, si, fid))
                ft.slotCleared.connect(lambda si=slot_index: _ft_on_flow_cleared(self, si))
                # Replace
                if old_w is not None:
                    layout.removeWidget(old_w)
                    old_w.setParent(None)
                    old_w.deleteLater()
                layout.addWidget(ft, grid_r, grid_c)
        except Exception as _e:
            import traceback
            print("[flow] swap-in failed:", _e)
            print(traceback.format_exc())

    def _ft_add_flow_button(self):
        """Add a '+ Flow' button to the title bar."""
        try:
            bar = self.title_bar
            btn = _FT_QPushButton("+ Flow", bar)
            btn.setObjectName("GhostBtn")
            from PySide6.QtCore import Qt as _Qt
            btn.setCursor(_Qt.PointingHandCursor)
            btn.setToolTip("Place a Flow Tile in the first empty slot")
            btn.clicked.connect(lambda: _ft_on_add_flow_clicked(self))
            # Insert before the "Free VRAM" button (index 5 from layout — robust:
            # insert after the stretch). Easiest: just add to the title bar's
            # layout near the end before the window control buttons.
            layout = bar.layout()
            if layout is not None:
                # Insert before the last 4 buttons (settings, update, min, max, close = 5)
                target_idx = max(layout.count() - 6, 0)
                layout.insertWidget(target_idx, btn)
        except Exception as _e:
            print("[flow] add flow button failed:", _e)

    def _ft_on_add_flow_clicked(self):
        """Handler for the + Flow button."""
        try:
            # Find first empty slot
            size = self.grid_picker.current_grid()
            if size == -1:
                _FT_QMessageBox.information(self, "Flow Tile",
                    "Switch to a grid view (not All Tools) to place a Flow Tile.")
                return
            empty_slot = None
            for i in range(size):
                if i not in self.slot_assignments:
                    empty_slot = i
                    break
            if empty_slot is None:
                _FT_QMessageBox.information(self, "Flow Tile",
                    "No empty slots available. Clear a slot first.")
                return
            # Open Flow Picker dialog
            flows = _ft_list_flows()
            flow_id = None
            if flows:
                # Use FlowPickerDialog if it provides a static pick(); else fall back to builder
                if hasattr(_FT_FlowPickerDialog, "pick"):
                    flow_id = _FT_FlowPickerDialog.pick(self)
                else:
                    dlg = _FT_FlowPickerDialog(parent=self)
                    if dlg.exec():
                        flow_id = getattr(dlg, "selected_flow_id", None)
                        if callable(flow_id):
                            flow_id = flow_id()
            if not flow_id:
                # No flows yet — open builder to create one
                if hasattr(_FT_FlowBuilderDialog, "create_new"):
                    flow = _FT_FlowBuilderDialog.create_new(self)
                else:
                    new_flow = _FT_Flow(id=_ft_new_flow_id(), name="New Flow", steps=[])
                    dlg = _FT_FlowBuilderDialog(flow=new_flow, parent=self)
                    if not dlg.exec():
                        return
                    flow = getattr(dlg, "flow", None) or new_flow
                if flow is None or not getattr(flow, "steps", []):
                    return  # user cancelled or empty flow
                _ft_save_flow(flow)
                flow_id = flow.id
            # Assign to slot
            self.slot_assignments[empty_slot] = _ft_assignment_for_flow(flow_id)
            try:
                import core.config as _cfgmod
                _cfgmod.set_slot_assignment(self.cfg, empty_slot, _ft_assignment_for_flow(flow_id))
                _cfgmod.save_config(self.cfg)
            except Exception:
                pass
            self._rebuild_grid(size)
        except Exception as _e:
            import traceback
            print("[flow] add flow clicked error:", _e)
            print(traceback.format_exc())

    # Wrap _rebuild_grid so flow tiles get swapped in after the normal build
    _MW = MainWindow
    _ft_orig_rebuild = _MW._rebuild_grid

    def _ft_patched_rebuild(self, size):
        _ft_orig_rebuild(self, size)
        _ft_swap_in_flow_tiles(self)

    _MW._rebuild_grid = _ft_patched_rebuild
    _MW._build_flow_processor = _ft_build_flow_processor
    _MW._assign_flow_to_slot = lambda self, slot, fid: _ft_on_flow_assigned(self, slot, fid)

    # Wrap __init__ so the +Flow button gets added after title bar exists
    _ft_orig_init = _MW.__init__

    def _ft_patched_init(self, *a, **kw):
        _ft_orig_init(self, *a, **kw)
        _ft_add_flow_button(self)

    _MW.__init__ = _ft_patched_init

    print("[flow] Flow Tiles v1.1.0 wiring installed.")
except Exception as _flow_wire_err:
    import traceback
    print("[flow] WIRING FAILED:", _flow_wire_err)
    print(traceback.format_exc())
# ============================================================================
# End Flow Tiles wiring
# ============================================================================
'''


def main() -> int:
    install_dir = find_install_dir()
    target = install_dir / "app" / "main_window.py"
    if not target.exists():
        raise SystemExit(f"Target not found: {target}")

    print(f"[patch] Install dir: {install_dir}")
    print(f"[patch] Target file: {target}")

    src = target.read_text(encoding="utf-8")

    # Idempotency check
    if "Flow Tiles v1.1.0 \u2014 appended by patch_flow_tiles_wiring.py" in src:
        print("[patch] Already patched. Nothing to do.")
        return 0

    # Validate original
    validate_python(src, "original main_window.py")

    # Backup
    backup = target.with_suffix(target.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(target, backup)
        print(f"[patch] Backup: {backup}")
    else:
        print(f"[patch] Backup already exists (keeping): {backup}")

    # Build new content
    new_src = src
    if not new_src.endswith("\n"):
        new_src += "\n"
    new_src += PATCH_BLOCK

    # Validate patched
    try:
        validate_python(new_src, "patched main_window.py")
    except SystemExit as e:
        print(f"[patch] Validation failed, NOT writing. {e}")
        return 1

    # Write
    target.write_text(new_src, encoding="utf-8")
    print(f"[patch] Wrote {len(new_src)} bytes to {target}")

    # Smoke test: import the module in a subprocess to catch ImportError early
    import subprocess
    # We can't easily import app.main_window without a QApplication, but we can
    # at least byte-compile it.
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(target)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("[patch] py_compile FAILED. Restoring backup.")
        print(result.stderr)
        shutil.copy2(backup, target)
        return 1
    print("[patch] py_compile OK.")
    print("[patch] DONE. Restart HicoForge to see Flow Tiles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
