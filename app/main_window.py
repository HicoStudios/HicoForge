"""
HicoForge main window — Chunk 4.

Wired end-to-end:
  - GPU detection + VRAM bar in the status footer
  - Model cache (lazy-load, LRU, idle auto-unload)
  - Background worker thread + job queue (now slot-aware for overrides)
  - Spandrel-based upscale processor working for all 9 spandrel tiles
    (UltraSharp, Ultramix, PurePhoto, TGHQFace8x, CountryRoads,
     RealESRGAN, AnimeSharp, DitherDeleter, RefocusCleanly)
  - Convert Format tile (PNG / JPG / WebP / TIFF; reads HEIC/HEIF/AVIF)
  - Per-tile live badges (pending count, active spinner, success checkmark)
  - Per-tile drop hint shows real-time progress and final output name
  - Outputs land in a per-tool subfolder next to the source
  - In-app model downloader + missing-model badge + before/after compare
  - Per-tile settings dialog for Convert (gear icon); persists in config.

Tools whose backend isn't wired yet (SCUNet, FBCNN, GFPGAN, Resize,
BG-Remove) will show a clear error when you drop on them.
That's Chunks 5 and 6.
"""

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    QScrollArea, QFrame, QGraphicsDropShadowEffect, QMessageBox, QFileDialog
)

from app import theme
from app.grid_picker import GridPicker
from app.tile import EmptyTile, Tile
from app.tool_picker import ToolPickerDialog
from app.status_bar import StatusBar
from app.download_dialog import DownloadDialog
from app.compare_dialog import CompareDialog, open_in_explorer
from app.convert_settings_dialog import ConvertSettingsDialog
from app.upscale_settings_dialog import UpscaleSettingsDialog
from app.resize_settings_dialog import ResizeSettingsDialog
from app.rembg_settings_dialog import RembgSettingsDialog
from app.app_settings_dialog import AppSettingsDialog
from app.history_dialog import HistoryDialog
from app.toast import ToastManager
from app.update_dialog import UpdateManager

from processors.tool_registry import (
    ALL_TOOLS, get_tool, tools_by_category, CATEGORY_ORDER, CATEGORY_COLOR
)
from processors.factory import build_processor, UnsupportedProcessorError
from core import config as cfgmod
from core.gpu_info import detect_gpu
from core.model_cache import ModelCache
from core.job_queue import JobQueue
from core.job_history import JobHistory
from core import queue_store


GRID_LAYOUTS = {
    1:  (1, 1),
    2:  (2, 1),
    4:  (2, 2),
    6:  (3, 2),
    8:  (4, 2),
    12: (4, 3),
}
ALL_MODE_COLS = 4


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1180, 760)

        self._drag_pos = None

        # --- Config ---
        self.cfg = cfgmod.load_config()
        self.slot_assignments: Dict[int, str] = cfgmod.get_slot_assignments(self.cfg)

        # --- GPU + cache + queue ---
        self.gpu = detect_gpu()
        self.model_cache = ModelCache(
            gpu=self.gpu,
            max_loaded=4,
            idle_unload_seconds=self.cfg.get("auto_unload_minutes", 10) * 60,
            status_callback=self._on_cache_status,
        )
        self.job_queue = JobQueue(build_processor_fn=self._build_processor_for_tool)
        self.job_queue.signals.started.connect(self._on_job_started)
        self.job_queue.signals.progress.connect(self._on_job_progress)
        self.job_queue.signals.finished.connect(self._on_job_finished)
        self.job_queue.signals.error.connect(self._on_job_error)
        self.job_queue.signals.queueChanged.connect(self._on_queue_changed)

        # Per-slot job history (latest source→output mapping for compare dialog)
        self.job_history = JobHistory()

        # Per-slot live state (for badges)
        self._slot_pending: Dict[int, int] = {}
        self._slot_active: Dict[int, bool] = {}
        self._slot_processed: Dict[int, int] = {}
        # Current tile widgets, keyed by slot_index
        self._tile_widgets: Dict[int, Tile] = {}

        # --- Shell ---
        self.shell = QWidget(self)
        self.shell.setObjectName("RootShell")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        self.shell.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(self.shell)

        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.title_bar = self._build_title_bar()
        shell_layout.addWidget(self.title_bar)

        self.grid_picker = GridPicker(self)
        self.grid_picker.gridChanged.connect(self._on_grid_changed)
        shell_layout.addWidget(self.grid_picker)

        self.grid_host = QScrollArea(self)
        self.grid_host.setWidgetResizable(True)
        self.grid_host.setFrameShape(QFrame.NoFrame)
        self.grid_host.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        shell_layout.addWidget(self.grid_host, 1)

        # --- Footer ---
        self.status_bar = StatusBar(self.gpu, self)
        self.status_bar.outputFolderClicked.connect(self._on_pick_central_output)
        self.status_bar.set_output_folder(self.cfg.get("central_output_folder", ""))
        shell_layout.addWidget(self.status_bar)

        # Restore last grid size
        last = self.cfg.get("last_grid_size", 4)
        if last == -1 or last in GRID_LAYOUTS:
            self.grid_picker.set_grid(last)
        self._rebuild_grid(self.grid_picker.current_grid())

        # Toast manager (Chunk 8)
        self.toasts = ToastManager(self)

        # Warn if models folder doesn't exist
        QTimer.singleShot(400, self._check_models_folder)

        # Restore any pending jobs from a previous session (Chunk 8)
        QTimer.singleShot(600, self._restore_pending_queue)

        # --- Auto-updater ---
        try:
            self.update_manager = UpdateManager(self)
            QTimer.singleShot(3000, self.update_manager.check_silently)
        except Exception as _upd_err:
            print(f"[updater] init failed: {_upd_err}")


    # ---- Updater ----
    def _open_update_check(self):
        """Title bar update button - force a manual check."""
        try:
            self.update_manager.check_manually()
        except Exception as _e:
            print(f"[updater] manual check failed: {_e}")

    # ---- Title bar ----
    def _build_title_bar(self):
        bar = QWidget(self)
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(46)

        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 0, 6, 0)
        h.setSpacing(10)

        mark = QLabel("●")
        mark.setStyleSheet(f"color: {theme.EMBER_ORANGE}; font-size: 12px;")
        h.addWidget(mark)

        title = QLabel("HicoForge")
        title.setObjectName("AppTitle")
        h.addWidget(title)

        sep = QLabel("·")
        sep.setStyleSheet(f"color: {theme.TEXT_DISABLED}; font-size: 14px;")
        h.addWidget(sep)

        subtitle = QLabel("SHAPE  IT.   SHARPEN  IT.")
        subtitle.setObjectName("AppSubtitle")
        h.addWidget(subtitle)

        h.addStretch(1)

        # Unload-all-models button
        unload_btn = QPushButton("Free VRAM")
        unload_btn.setObjectName("GhostBtn")
        unload_btn.setCursor(Qt.PointingHandCursor)
        unload_btn.setToolTip("Unload all currently loaded models")
        unload_btn.clicked.connect(self._unload_all_models)
        h.addWidget(unload_btn)

        history_btn = QPushButton("✎")
        history_btn.setObjectName("WinBtn")
        history_btn.setCursor(Qt.PointingHandCursor)
        history_btn.setToolTip("Job history")
        history_btn.clicked.connect(self._open_history)
        h.addWidget(history_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("WinBtn")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._open_app_settings)
        h.addWidget(settings_btn)

        update_btn = QPushButton("↻")
        update_btn.setObjectName("WinBtn")
        update_btn.setCursor(Qt.PointingHandCursor)
        update_btn.setToolTip("Check for updates")
        update_btn.clicked.connect(self._open_update_check)
        h.addWidget(update_btn)

        min_btn = QPushButton("—")
        min_btn.setObjectName("WinBtn")
        min_btn.setCursor(Qt.PointingHandCursor)
        min_btn.clicked.connect(self.showMinimized)
        h.addWidget(min_btn)

        max_btn = QPushButton("▢")
        max_btn.setObjectName("WinBtn")
        max_btn.setCursor(Qt.PointingHandCursor)
        max_btn.clicked.connect(self._toggle_maximize)
        h.addWidget(max_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("WinBtnClose")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        h.addWidget(close_btn)

        return bar

    # ---- Grid handling ----
    def _on_grid_changed(self, size: int):
        self.cfg["last_grid_size"] = size
        cfgmod.save_config(self.cfg)
        self._rebuild_grid(size)

    def _rebuild_grid(self, size: int):
        old = self.grid_host.takeWidget()
        if old is not None:
            old.deleteLater()

        # Drop old tile widget refs (they'll be recreated)
        self._tile_widgets.clear()

        container = QWidget()
        container.setStyleSheet("background: transparent;")

        if size == -1:
            self._build_all_mode(container)
        else:
            self._build_grid_mode(container, size)

        self.grid_host.setWidget(container)
        self._refresh_footer_summary()

    def _build_grid_mode(self, container, size):
        gl = QGridLayout(container)
        gl.setContentsMargins(20, 16, 20, 20)
        gl.setSpacing(14)

        cols, _rows = GRID_LAYOUTS[size]

        for i in range(size):
            r = i // cols
            c = i % cols
            tool_id = self.slot_assignments.get(i)
            tool = get_tool(tool_id) if tool_id else None
            if tool:
                tile = Tile(i, tool, container)
                tile.clearRequested.connect(self._on_clear_slot)
                tile.settingsRequested.connect(self._on_tile_settings)
                tile.filesDropped.connect(self._on_files_dropped)
                tile.reassignRequested.connect(self._on_choose_slot)
                tile.downloadRequested.connect(self._on_download_requested)
                tile.showLastOutputRequested.connect(self._on_show_last_output)
                tile.revealLastOutputRequested.connect(self._on_reveal_last_output)
                # Restore badge state
                tile.set_queue_state(
                    self._slot_active.get(i, False),
                    self._slot_pending.get(i, 0),
                    self._slot_processed.get(i, 0),
                )
                # Initialize missing-model badge
                tile.set_model_missing(self._is_model_missing(tool))
                # Initialize click-to-compare state
                tile.set_has_last_output(self.job_history.last(i) is not None)
                # Show effective scale + format on the idle drop hint
                tile.set_idle_hint(self._idle_hint_for_slot(i, tool))
                self._tile_widgets[i] = tile
            else:
                tile = EmptyTile(i, container)
                tile.chooseRequested.connect(self._on_choose_slot)
            gl.addWidget(tile, r, c)

        for c in range(cols):
            gl.setColumnStretch(c, 1)

    def _build_all_mode(self, container):
        v = QVBoxLayout(container)
        v.setContentsMargins(20, 16, 20, 20)
        v.setSpacing(16)

        grouped = tools_by_category()
        for cat in CATEGORY_ORDER:
            items = grouped.get(cat, [])
            if not items:
                continue
            header = QLabel(cat)
            header.setStyleSheet(
                f"color: {CATEGORY_COLOR.get(cat, theme.EMBER_GOLD)}; "
                f"font-size: 10px; font-weight: 700; letter-spacing: 2px; "
                f"background: transparent; padding: 4px 2px;"
            )
            v.addWidget(header)

            cat_grid = QGridLayout()
            cat_grid.setSpacing(14)
            for idx, tool in enumerate(items):
                r = idx // ALL_MODE_COLS
                c = idx % ALL_MODE_COLS
                # In All-mode we use a stable synthetic slot keyed off the tool id
                # so progress/finished/error callbacks can find the tile widget.
                synth_slot = self._synthetic_slot_for(tool.id)
                tile = Tile(synth_slot, tool, container)
                tile.filesDropped.connect(self._on_files_dropped_all_mode)
                tile.settingsRequested.connect(self._on_tile_settings)
                tile.showLastOutputRequested.connect(self._on_show_last_output)
                tile.revealLastOutputRequested.connect(self._on_reveal_last_output)
                tile.downloadRequested.connect(
                    lambda _s, t=tool: self._download_model_for_tool(t)
                )
                tile.set_model_missing(self._is_model_missing(tool))
                # Restore live state (in case a job from this tool is still pending)
                tile.set_queue_state(
                    self._slot_active.get(synth_slot, False),
                    self._slot_pending.get(synth_slot, 0),
                    self._slot_processed.get(synth_slot, 0),
                )
                tile.set_has_last_output(
                    self.job_history.last(synth_slot) is not None
                )
                self._tile_widgets[synth_slot] = tile
                cat_grid.addWidget(tile, r, c)
            for col in range(ALL_MODE_COLS):
                cat_grid.setColumnStretch(col, 1)
            v.addLayout(cat_grid)

        v.addStretch(1)

    # ---- Slot interactions ----
    def _on_choose_slot(self, slot_index: int):
        current = self.slot_assignments.get(slot_index)
        chosen = ToolPickerDialog.pick(self, slot_index, current)
        if chosen and chosen != current:
            self.slot_assignments[slot_index] = chosen
            cfgmod.set_slot_assignment(self.cfg, slot_index, chosen)
            # New tool in this slot — wipe any leftover per-tile overrides
            self._set_tile_settings(slot_index, {})
            cfgmod.save_config(self.cfg)
            self._rebuild_grid(self.grid_picker.current_grid())
            tool = get_tool(chosen)
            self.status_bar.set_status(f"Assigned {tool.name} to slot {slot_index + 1}")

    def _on_clear_slot(self, slot_index: int):
        if slot_index in self.slot_assignments:
            del self.slot_assignments[slot_index]
            cfgmod.set_slot_assignment(self.cfg, slot_index, None)
            # Drop any per-tile setting overrides for this slot
            self._set_tile_settings(slot_index, {})
            cfgmod.save_config(self.cfg)
            # Clear live state for the slot
            self._slot_pending.pop(slot_index, None)
            self._slot_active.pop(slot_index, None)
            self._slot_processed.pop(slot_index, None)
            self._rebuild_grid(self.grid_picker.current_grid())
            self.status_bar.set_status(f"Cleared slot {slot_index + 1}")

    def _on_tile_settings(self, slot_index: int):
        tool_id = self.slot_assignments.get(slot_index)
        if tool_id is None and slot_index >= 1000:
            tool_id = self._tool_id_for_synthetic(slot_index)
        tool = get_tool(tool_id) if tool_id else None
        if not tool:
            return

        # Convert Format gets its own focused dialog.
        if tool.processor_key == "pil_convert":
            current = self._get_tile_settings(slot_index) or dict(tool.default_settings or {})
            dlg = ConvertSettingsDialog(tool.name, current, parent=self)
            if dlg.exec():
                self._set_tile_settings(slot_index, dlg.result_settings())
                fmt = dlg.result_settings().get("target_format", "png").upper()
                self.status_bar.set_status(f"{tool.name}: output set to {fmt}")
                self._rebuild_grid(self.grid_picker.current_grid())
            return

        # Spandrel-based tools (upscale + cleanup) get the full settings dialog.
        if tool.processor_key == "spandrel_upscale":
            current = self._get_tile_settings(slot_index) or {}
            dlg = UpscaleSettingsDialog(tool, current, parent=self)
            if dlg.exec():
                self._set_tile_settings(slot_index, dlg.result_settings())
                s = dlg.result_settings()
                scale = s.get("output_scale", tool.default_output_scale)
                fmt = s.get("target_format", tool.default_format).upper()
                self.status_bar.set_status(
                    f"{tool.name}: {scale:g}× → {fmt}"
                )
                self._rebuild_grid(self.grid_picker.current_grid())
            return

        # Resize utility
        if tool.processor_key == "pil_resize":
            current = self._get_tile_settings(slot_index) or dict(tool.default_settings or {})
            dlg = ResizeSettingsDialog(tool, current, parent=self)
            if dlg.exec():
                self._set_tile_settings(slot_index, dlg.result_settings())
                s = dlg.result_settings()
                tgt = s.get("target", "max_2048")
                self.status_bar.set_status(f"{tool.name}: target {tgt}")
                self._rebuild_grid(self.grid_picker.current_grid())
            return

        # Background removal
        if tool.processor_key == "rembg":
            current = self._get_tile_settings(slot_index) or dict(tool.default_settings or {})
            dlg = RembgSettingsDialog(tool, current, parent=self)
            if dlg.exec():
                self._set_tile_settings(slot_index, dlg.result_settings())
                s = dlg.result_settings()
                m = s.get("rembg_model", "u2net")
                self.status_bar.set_status(f"{tool.name}: engine {m}")
                self._rebuild_grid(self.grid_picker.current_grid())
            return

        QMessageBox.information(
            self, f"{tool.name} settings",
            (
                f"No settings dialog for this backend yet.\n\n"
                f"Tool: {tool.name}\n"
                f"Processor: {tool.processor_key}"
            ),
        )

    def _on_files_dropped(self, slot_index: int, files: list[Path]):
        tool_id = self.slot_assignments.get(slot_index)
        tool = get_tool(tool_id) if tool_id else None
        if not tool:
            return
        # Pre-check: backend supported?
        if tool.processor_key not in {"spandrel_upscale", "pil_convert", "pil_resize", "rembg"}:
            QMessageBox.information(
                self, f"{tool.name} not ready yet",
                (
                    f"{tool.name} uses the '{tool.processor_key}' backend, which "
                    "isn't wired up."
                ),
            )
            return
        # Pre-check: model file present?
        model_path = Path(self.cfg["models_folder"]) / (tool.model_filename or "")
        if tool.model_filename and not model_path.exists():
            self._prompt_download(slot_index, tool, files)
            return

        # Enqueue
        self._slot_pending[slot_index] = self._slot_pending.get(slot_index, 0) + len(files)
        self._refresh_tile_badge(slot_index)
        self.job_queue.enqueue_many(slot_index, tool_id, files)
        self.status_bar.set_status(
            f"{tool.name}: queued {len(files)} image{'s' if len(files) != 1 else ''}"
        )

    def _on_files_dropped_all_mode(self, slot_index: int, files: list[Path]):
        sender = self.sender()
        tool = sender.tool if sender and hasattr(sender, "tool") else None
        if tool is None:
            return
        # slot_index passed in is the tile's synthetic slot (set at build time).
        synthetic_slot = slot_index if slot_index >= 1000 else self._synthetic_slot_for(tool.id)
        # Backend check
        if tool.processor_key not in {"spandrel_upscale", "pil_convert", "pil_resize", "rembg"}:
            QMessageBox.information(
                self, f"{tool.name} not ready yet",
                f"{tool.name} uses the '{tool.processor_key}' backend, which isn't wired up."
            )
            return
        model_path = Path(self.cfg["models_folder"]) / (tool.model_filename or "")
        if tool.model_filename and not model_path.exists():
            if not self._download_model_for_tool(tool):
                return
            # Refresh model path now that it should exist
            if not model_path.exists():
                return
        # Update tile state immediately so the badge appears on drop
        self._slot_pending[synthetic_slot] = (
            self._slot_pending.get(synthetic_slot, 0) + len(files)
        )
        self._refresh_tile_badge(synthetic_slot)
        self.job_queue.enqueue_many(synthetic_slot, tool.id, files)
        self.status_bar.set_status(
            f"{tool.name}: queued {len(files)} image{'s' if len(files) != 1 else ''} (All-mode)"
        )

    # ---- Worker callbacks ----
    def _on_job_started(self, slot: int, source: str):
        self._slot_active[slot] = True
        self._refresh_tile_badge(slot)
        tile = self._tile_widgets.get(slot)
        name = Path(source).name
        if tile:
            tile.flash_progress(f"⟳ {name}")
        self.status_bar.set_status(f"Processing {name}…")

    def _on_job_progress(self, slot: int, source: str, message: str):
        tile = self._tile_widgets.get(slot)
        name = Path(source).name
        if tile:
            tile.flash_progress(f"⟳ {name} · {message}")
        self.status_bar.set_status(f"{name} · {message}")

    def _on_job_finished(self, slot: int, source: str, output: str):
        # Pending count down
        self._slot_pending[slot] = max(0, self._slot_pending.get(slot, 0) - 1)
        self._slot_active[slot] = self._slot_pending[slot] > 0
        self._slot_processed[slot] = self._slot_processed.get(slot, 0) + 1
        self._refresh_tile_badge(slot)
        # Record for compare dialog + persistent history
        tool_id = self.slot_assignments.get(slot) or self._tool_id_for_synthetic(slot)
        if tool_id:
            self.job_history.record(slot, source, output, tool_id, success=True)
        tile = self._tile_widgets.get(slot)
        if tile:
            tile.flash_done(Path(output).name)
            tile.set_has_last_output(True)
        out_name = Path(output).name
        self.status_bar.set_status(f"Saved {out_name}")
        # Toast: only when the slot is now idle (avoid spamming during long batches)
        if self._slot_pending.get(slot, 0) == 0:
            self.toasts.show_toast(f"Saved {out_name}", kind="success")

    def _on_job_error(self, slot: int, source: str, error: str):
        self._slot_pending[slot] = max(0, self._slot_pending.get(slot, 0) - 1)
        self._slot_active[slot] = self._slot_pending[slot] > 0
        self._refresh_tile_badge(slot)
        tile = self._tile_widgets.get(slot)
        name = Path(source).name
        if tile:
            tile.flash_error(f"{name}: {error[:80]}")
        self.status_bar.set_status(f"Error on {name}: {error[:100]}")
        # Record failure in persistent history
        tool_id = self.slot_assignments.get(slot) or self._tool_id_for_synthetic(slot)
        if tool_id:
            self.job_history.record(slot, source, "", tool_id,
                                    success=False, error=error)
        self.toasts.show_toast(f"Error on {name}: {error[:80]}", kind="error")

    def _on_queue_changed(self, pending: int, processed: int):
        self.status_bar.set_queue(pending, processed)

    def _refresh_tile_badge(self, slot: int):
        tile = self._tile_widgets.get(slot)
        if not tile:
            return
        tile.set_queue_state(
            self._slot_active.get(slot, False),
            self._slot_pending.get(slot, 0),
            self._slot_processed.get(slot, 0),
        )

    # ---- Download + compare handlers ----
    def _is_model_missing(self, tool) -> bool:
        if not tool.model_filename:
            return False
        return not (Path(self.cfg["models_folder"]) / tool.model_filename).exists()

    def _refresh_all_missing_badges(self):
        for slot, tile in self._tile_widgets.items():
            tool = get_tool(self.slot_assignments.get(slot))
            if tool:
                tile.set_model_missing(self._is_model_missing(tool))

    def _on_download_requested(self, slot_index: int):
        tool_id = self.slot_assignments.get(slot_index)
        tool = get_tool(tool_id) if tool_id else None
        if not tool:
            return
        self._download_model_for_tool(tool)

    def _download_model_for_tool(self, tool) -> bool:
        """Open the download dialog. Returns True if file is present afterwards."""
        if not tool.download_url:
            QMessageBox.information(
                self, "No download available",
                f"{tool.name} doesn't have a built-in download URL configured.\n\n"
                f"Place {tool.model_filename} into:\n  {self.cfg['models_folder']}"
            )
            return False
        models_folder = Path(self.cfg["models_folder"])
        ok = DownloadDialog.run(self, tool, models_folder)
        # Refresh badges either way (a partial file might still be missing)
        self._refresh_all_missing_badges()
        return ok and (models_folder / tool.model_filename).exists()

    def _prompt_download(self, slot_index: int, tool, pending_files: list):
        """User dropped images but model is missing — offer to download then re-enqueue."""
        if not tool.download_url:
            QMessageBox.warning(
                self, "Model file not found",
                (
                    f"{tool.name} needs:\n  {tool.model_filename}\n\n"
                    f"Looked in:\n  {self.cfg['models_folder']}\n\n"
                    "No built-in download URL for this tool yet. Drop the file "
                    "into the models folder manually."
                ),
            )
            return
        size_txt = (
            f" ({tool.download_size_mb} MB)" if tool.download_size_mb else ""
        )
        resp = QMessageBox.question(
            self, "Download model?",
            (
                f"{tool.name} needs {tool.model_filename}{size_txt}.\n\n"
                f"Download it now into:\n  {self.cfg['models_folder']}\n\n"
                "After it finishes, the dropped images will be queued automatically."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if resp != QMessageBox.Yes:
            return
        if self._download_model_for_tool(tool):
            # Re-enqueue the originally dropped files
            self._slot_pending[slot_index] = self._slot_pending.get(slot_index, 0) + len(pending_files)
            self._refresh_tile_badge(slot_index)
            self.job_queue.enqueue_many(slot_index, tool.id, pending_files)
            self.status_bar.set_status(
                f"{tool.name}: queued {len(pending_files)} image"
                f"{'s' if len(pending_files) != 1 else ''}"
            )

    def _on_show_last_output(self, slot_index: int):
        rec = self.job_history.last(slot_index)
        if not rec:
            return
        tool = get_tool(rec.tool_id)
        title = f"{tool.name if tool else 'Result'} — {rec.source.name}"
        CompareDialog.show_compare(self, rec.source, rec.output, title)

    def _on_reveal_last_output(self, slot_index: int):
        rec = self.job_history.last(slot_index)
        if not rec:
            return
        open_in_explorer(rec.output)

    # ---- Processor factory hook ----
    def _build_processor_for_tool(self, tool_id: str, slot_index: int = -1):
        tool = get_tool(tool_id)
        if tool is None:
            raise ValueError(f"Unknown tool_id: {tool_id}")
        models_folder = Path(self.cfg.get("models_folder", ""))
        overrides = self._get_tile_settings(slot_index)
        central_str = (self.cfg.get("central_output_folder") or "").strip()
        central = Path(central_str) if central_str else None
        return build_processor(
            tool, models_folder, self.model_cache, self.gpu,
            overrides=overrides,
            central_folder=central,
        )

    # ---- Central output folder ----
    def _on_pick_central_output(self):
        current = self.cfg.get("central_output_folder", "") or ""
        # Offer a 3-way choice: pick / clear / cancel
        if current:
            box = QMessageBox(self)
            box.setWindowTitle("Output folder")
            box.setText(
                f"Central output folder is currently:\n\n{current}\n\n"
                "Outputs land in <folder>/<tool>/<mirrored source path>/file.png"
            )
            change_btn = box.addButton("Change…", QMessageBox.AcceptRole)
            clear_btn = box.addButton("Save next to source", QMessageBox.DestructiveRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is clear_btn:
                self.cfg["central_output_folder"] = ""
                cfgmod.save_config(self.cfg)
                self.status_bar.set_output_folder("")
                self.status_bar.set_status("Outputs will save next to source")
                return
            if box.clickedButton() is not change_btn:
                return
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose central output folder",
            current or str(Path.home()),
        )
        if chosen:
            self.cfg["central_output_folder"] = chosen
            cfgmod.save_config(self.cfg)
            self.status_bar.set_output_folder(chosen)
            self.status_bar.set_status(f"Output folder set: {chosen}")

    # ---- Drop-hint helper ----
    def _idle_hint_for_slot(self, slot_index: int, tool) -> str:
        """Build the small grey hint shown under the tile glyph.

        Examples: '4× → PNG', '2× → JPG 90', 'WebP', '1× preserve'.
        """
        if tool is None:
            return ""
        s = dict(tool.default_settings or {})
        s.update(self._get_tile_settings(slot_index))

        scale = float(s.get("output_scale", tool.default_output_scale))
        fmt = (s.get("target_format") or s.get("output_format")
               or tool.default_format or "preserve").lower()
        fmt_disp = {
            "jpg": "JPG", "jpeg": "JPG", "png": "PNG",
            "webp": "WebP", "tiff": "TIFF", "tif": "TIFF",
            "preserve": "preserve",
        }.get(fmt, fmt.upper())

        # Quality tag only when meaningful and overridden from defaults
        qual = None
        if fmt in ("jpg", "jpeg"):
            qual = int(s.get("jpg_quality", 95))
        elif fmt == "webp":
            qual = int(s.get("webp_quality", 92))

        if tool.processor_key == "pil_convert":
            base = f"→ {fmt_disp}"
        else:
            base = f"{scale:g}× → {fmt_disp}"
        if qual is not None and qual != 95 and qual != 92:
            base += f" {qual}"
        return base.upper()

    # ---- Per-tile setting overrides ----
    def _get_tile_settings(self, slot_index: int) -> dict:
        """Return any per-slot setting overrides from config."""
        if slot_index is None or slot_index < 0:
            return {}
        all_settings = self.cfg.get("tile_settings", {})
        # Config JSON stores keys as strings
        return dict(all_settings.get(str(slot_index), {}))

    def _set_tile_settings(self, slot_index: int, settings: dict) -> None:
        if slot_index is None or slot_index < 0:
            return
        all_settings = self.cfg.setdefault("tile_settings", {})
        if settings:
            all_settings[str(slot_index)] = settings
        else:
            all_settings.pop(str(slot_index), None)
        cfgmod.save_config(self.cfg)

    # ---- Cache + status helpers ----
    def _on_cache_status(self, message: str):
        # Called from cache worker thread → use QTimer to bounce to UI thread.
        QTimer.singleShot(0, lambda: self.status_bar.set_status(message))

    def _unload_all_models(self):
        n = self.model_cache.unload_all()
        if n == 0:
            self.status_bar.set_status("No models were loaded")
        else:
            self.status_bar.set_status(f"Unloaded {n} model(s)")

    def _check_models_folder(self):
        folder = Path(self.cfg.get("models_folder", ""))
        if not folder.exists():
            QMessageBox.information(
                self, "Models folder not found",
                (
                    f"HicoForge expected to find your spandrel models at:\n\n"
                    f"  {folder}\n\n"
                    "That path doesn't exist yet. Either create it and drop your "
                    ".pth/.safetensors files in, or change the path in Settings "
                    "(coming in Chunk 7). For now, individual tiles will pop a "
                    "specific 'model not found' warning when you drop on them."
                ),
            )

    def _refresh_footer_summary(self):
        size = self.grid_picker.current_grid()
        if size == -1:
            self.status_bar.set_status(
                f"All tools mode · {len(ALL_TOOLS)} tools · drop images on any tool"
            )
        else:
            assigned = sum(1 for i in range(size) if i in self.slot_assignments)
            self.status_bar.set_status(
                f"{size}-tile layout · {assigned}/{size} slots assigned"
            )

    # ---- App settings / history (Chunk 7 + 8) ----
    def _open_app_settings(self):
        dlg = AppSettingsDialog(self.cfg, parent=self)
        if not dlg.exec():
            return
        new_cfg = dlg.result_settings()
        # Detect what actually changed so we can react
        old_models = self.cfg.get("models_folder")
        old_output = self.cfg.get("central_output_folder")
        old_unload = self.cfg.get("auto_unload_minutes")

        # Merge into the live config dict (preserve unrelated keys like slot_assignments)
        self.cfg.update(new_cfg)
        cfgmod.save_config(self.cfg)

        # Apply runtime changes
        if old_output != self.cfg.get("central_output_folder"):
            self.status_bar.set_output_folder(self.cfg.get("central_output_folder", ""))
        if old_models != self.cfg.get("models_folder"):
            # Re-check missing-model badges against the new folder
            self._refresh_all_missing_badges()
        if old_unload != self.cfg.get("auto_unload_minutes"):
            try:
                self.model_cache._idle_seconds = int(self.cfg["auto_unload_minutes"]) * 60
            except Exception:
                pass

        self.status_bar.set_status("Settings saved")
        self.toasts.show_toast("Settings saved", kind="info")

    def _open_history(self):
        dlg = HistoryDialog(self.job_history, parent=self)
        dlg.exec()

    # ---- Pending-queue persistence (Chunk 8) ----
    def _restore_pending_queue(self):
        items = queue_store.load_pending()
        if not items:
            return
        n = self.job_queue.restore_pending(items)
        # Clear the disk store — the queue now owns these jobs in-memory
        queue_store.clear_pending()
        # Refresh tile badges for real slots whose jobs were restored
        for d in items:
            slot = int(d.get("slot_index", -1))
            if 0 <= slot < 12:
                self._slot_pending[slot] = self._slot_pending.get(slot, 0) + 1
                self._refresh_tile_badge(slot)
        if n > 0:
            self.status_bar.set_status(
                f"Resumed {n} pending job{'s' if n != 1 else ''} from last session"
            )
            self.toasts.show_toast(
                f"Resumed {n} pending job{'s' if n != 1 else ''}", kind="info"
            )

    def _synthetic_slot_for(self, tool_id: str) -> int:
        """Stable synthetic slot index for an All-mode tile.

        Uses a hash-stable formula keyed off the tool_id. Range is 1000..1999
        so it never collides with real slots (0..11). Stable within a process.
        """
        return 1000 + abs(hash(tool_id)) % 1000

    def _tool_id_for_synthetic(self, slot_index: int) -> Optional[str]:
        """All-mode jobs use synthetic slot indices > 999. Walk every tool to find
        the one whose hash matches — slow but only used for history bookkeeping."""
        if slot_index < 1000:
            return None
        from processors.tool_registry import ALL_TOOLS
        for t in ALL_TOOLS:
            if self._synthetic_slot_for(t.id) == slot_index:
                return t.id
        return None

    # ---- Resize hook for toast positioning ----
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.reposition_on_resize()

    # ---- Shutdown ----
    def closeEvent(self, event):
        # Persist pending queue (Chunk 8)
        try:
            items = self.job_queue.snapshot_pending()
            if items:
                queue_store.save_pending(items)
            else:
                queue_store.clear_pending()
        except Exception:
            pass
        try:
            self.job_queue.shutdown()
        except Exception:
            pass
        try:
            self.model_cache.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    # ---- Frameless drag/maximize ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.title_bar.geometry().contains(event.position().toPoint()):
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if self.title_bar.geometry().contains(event.position().toPoint()):
            self._toggle_maximize()

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()


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
