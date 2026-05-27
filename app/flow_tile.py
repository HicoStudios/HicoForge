"""
app/flow_tile.py
----------------
FlowTile widget for HicoForge v1.1.0.

A FlowTile is a grid slot widget that holds a saved Flow rather than a
single tool.  It is visually distinguished from a regular Tile by:

  • A chain icon (⛓) in the top-left corner
  • An accent border rendered in EMBER_ORANGE (or FLOW_ACCENT if defined)
  • A step-count badge and one-line step preview inside the tile body
  • A full-width progress bar + status text during an active run

Drag-drop behaviour mirrors the existing Tile widget: the user drops one
or more image files onto the tile to start the flow.

When clicked:
  • Empty slot  → opens FlowPickerDialog (choose or create a flow)
  • Assigned    → opens FlowBuilderDialog to edit the flow

Right-click context menu: Edit Flow | Change Flow | Clear Slot | Export JSON

Integration note: FlowTile is intended to be instantiated and placed in
MainWindow's grid alongside regular Tile widgets.  Slot-persistence should
be stored under config["flow_tile_slots"][slot_key] = flow_id.  Wire this
up in the main-window patch script.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QSize, Signal, QMimeData
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QDragEnterEvent,
    QDropEvent, QMouseEvent, QContextMenuEvent,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QSizePolicy, QMenu, QFileDialog, QMessageBox,
)

from app import theme
from core.flow_engine import Flow, FlowEngine
from core.flow_store import (
    get_flow, save_flow, delete_flow, export_flow,
    list_flows, new_flow_id,
)

# Accent color for the chain border.  Falls back to EMBER_ORANGE.
try:
    FLOW_ACCENT: str = theme.FLOW_ACCENT  # type: ignore[attr-defined]
except AttributeError:
    FLOW_ACCENT: str = theme.EMBER_ORANGE  # type: ignore[assignment]

_CHAIN_ICON = "⛓"
_BORDER_WIDTH = 3


class FlowTile(QWidget):
    """A grid slot that runs a saved Flow chain on dropped images.

    Signals
    -------
    flowAssigned(flow_id)
        Emitted after the user assigns (or changes) the flow in this slot.
    slotCleared()
        Emitted when the user clears the slot via the context menu.
    runStarted()
        Emitted when a flow run begins.
    runFinished(summary_json)
        Emitted when a flow run ends.  summary_json is JSON-encoded.
    """

    flowAssigned = Signal(str)
    slotCleared = Signal()
    runStarted = Signal()
    runFinished = Signal(str)

    def __init__(
        self,
        slot_key: str = "",
        build_processor_fn: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Parameters
        ----------
        slot_key:
            Persistent identifier for this grid slot (e.g. "row0_col2").
        build_processor_fn:
            Callable(tool_id, overrides) -> BaseProcessor. Supplied by the
            host (MainWindow); forwarded to FlowEngine when a run starts.
            Without it, the tile renders but cannot execute flows.
        """
        super().__init__(parent)
        self._slot_key = slot_key          # e.g. "row0_col2"
        self._build_processor_fn = build_processor_fn
        self._flow: Optional[Flow] = None
        self._engine: Optional[FlowEngine] = None
        self._running = False
        self._status_text = ""
        self._progress_value = 0           # 0-100

        self.setAcceptDrops(True)
        self.setMinimumSize(120, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign_flow(self, flow_id: str) -> None:
        """Bind this tile to an existing saved flow by id."""
        flow = get_flow(flow_id)
        if flow is None:
            print(f"[flow] FlowTile.assign_flow: unknown id '{flow_id}'")
            return
        self._flow = flow
        self._refresh_display()
        self.flowAssigned.emit(flow_id)

    def clear_slot(self) -> None:
        """Detach the current flow from this tile."""
        self._flow = None
        self._refresh_display()
        self.slotCleared.emit()

    @property
    def flow(self) -> Optional[Flow]:
        return self._flow

    @property
    def slot_key(self) -> str:
        return self._slot_key

    def set_slot_key(self, key: str) -> None:
        self._slot_key = key

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_BORDER_WIDTH + 4, _BORDER_WIDTH + 4,
                                  _BORDER_WIDTH + 4, _BORDER_WIDTH + 4)
        outer.setSpacing(4)

        # Header row: chain icon + flow name
        header = QHBoxLayout()
        header.setSpacing(6)

        self._icon_label = QLabel(_CHAIN_ICON)
        self._icon_label.setFont(QFont("Segoe UI Emoji", 14))
        self._icon_label.setFixedWidth(22)

        self._name_label = QLabel("New Flow Tile")
        self._name_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._name_label.setStyleSheet(f"color: {FLOW_ACCENT};")
        self._name_label.setWordWrap(False)
        self._name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._badge_label = QLabel("")
        self._badge_label.setFont(QFont("Segoe UI", 8))
        self._badge_label.setStyleSheet(
            f"color: #fff; background: {FLOW_ACCENT}; border-radius: 7px; padding: 1px 6px;"
        )
        self._badge_label.hide()

        header.addWidget(self._icon_label)
        header.addWidget(self._name_label, 1)
        header.addWidget(self._badge_label)
        outer.addLayout(header)

        # Step preview line
        self._preview_label = QLabel("")
        self._preview_label.setFont(QFont("Segoe UI", 8))
        self._preview_label.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        self._preview_label.setWordWrap(True)
        outer.addWidget(self._preview_label)

        outer.addStretch(1)

        # Status text (shown during run)
        self._status_label = QLabel("")
        self._status_label.setFont(QFont("Segoe UI", 8))
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.hide()
        outer.addWidget(self._status_label)

        # Progress bar (shown during run, hidden otherwise)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: #333; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {FLOW_ACCENT}; border-radius: 3px; }}"
        )
        self._progress_bar.hide()
        outer.addWidget(self._progress_bar)

        self.setLayout(outer)
        self._refresh_display()

    # ------------------------------------------------------------------
    # Display refresh
    # ------------------------------------------------------------------

    def _refresh_display(self) -> None:
        if self._flow is None:
            self._name_label.setText("New Flow Tile")
            self._name_label.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
            self._badge_label.hide()
            self._preview_label.setText("Drop images to run · click to assign")
        else:
            self._name_label.setText(self._flow.name)
            self._name_label.setStyleSheet(f"color: {FLOW_ACCENT};")
            n = len(self._flow.steps)
            self._badge_label.setText(f"{n} step{'s' if n != 1 else ''}")
            self._badge_label.show()
            preview = self._flow.step_preview(max_steps=4)
            self._preview_label.setText(preview)
        self.update()

    # ------------------------------------------------------------------
    # Custom painting (accent border)
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(FLOW_ACCENT), _BORDER_WIDTH)
        painter.setPen(pen)
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        half = _BORDER_WIDTH // 2
        painter.drawRoundedRect(
            half, half,
            self.width() - _BORDER_WIDTH,
            self.height() - _BORDER_WIDTH,
            6, 6,
        )

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._running:
            if self._flow is None:
                self._open_flow_picker()
            else:
                self._open_flow_builder()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)

        if self._flow is not None:
            act_edit = menu.addAction("Edit Flow")
            act_change = menu.addAction("Change Flow")
            act_export = menu.addAction("Export Flow JSON…")
            menu.addSeparator()
            act_clear = menu.addAction("Clear Slot")

            act_edit.triggered.connect(self._open_flow_builder)
            act_change.triggered.connect(self._open_flow_picker)
            act_export.triggered.connect(self._on_export_flow)
            act_clear.triggered.connect(self._on_clear_slot)
        else:
            act_assign = menu.addAction("Assign Flow…")
            act_assign.triggered.connect(self._open_flow_picker)

        menu.exec(event.globalPos())

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(self._is_image_url(u) for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if self._running:
            return
        urls = event.mimeData().urls()
        paths = [
            u.toLocalFile() for u in urls
            if self._is_image_url(u)
        ]
        if not paths:
            return
        event.acceptProposedAction()
        self._start_run(paths)

    @staticmethod
    def _is_image_url(url) -> bool:
        ext = Path(url.toLocalFile()).suffix.lower()
        return ext in {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}

    # ------------------------------------------------------------------
    # Flow picker (choose existing or create new)
    # ------------------------------------------------------------------

    def _open_flow_picker(self) -> None:
        """Open the FlowPickerDialog; assign whatever the user selects."""
        from app.flow_builder_dialog import FlowPickerDialog  # local import to avoid circular
        dlg = FlowPickerDialog(parent=self)
        if dlg.exec():
            selected_id = dlg.selected_flow_id()
            if selected_id:
                self.assign_flow(selected_id)
            elif dlg.wants_new_flow():
                self._create_and_assign_new_flow()

    def _create_and_assign_new_flow(self) -> None:
        """Create a blank flow, open the builder, then assign if saved."""
        from app.flow_builder_dialog import FlowBuilderDialog
        from core.flow_engine import Flow
        blank = Flow(id=new_flow_id(), name="New Flow")
        dlg = FlowBuilderDialog(flow=blank, parent=self)
        if dlg.exec():
            saved = dlg.get_flow()
            save_flow(saved)
            self._flow = saved
            self._refresh_display()
            self.flowAssigned.emit(saved.id)

    # ------------------------------------------------------------------
    # Flow builder (edit existing)
    # ------------------------------------------------------------------

    def _open_flow_builder(self) -> None:
        """Open FlowBuilderDialog to edit the currently assigned flow."""
        if self._flow is None:
            return
        from app.flow_builder_dialog import FlowBuilderDialog
        dlg = FlowBuilderDialog(flow=self._flow, parent=self)
        if dlg.exec():
            updated = dlg.get_flow()
            save_flow(updated)
            self._flow = updated
            self._refresh_display()

    # ------------------------------------------------------------------
    # Context menu actions
    # ------------------------------------------------------------------

    def _on_clear_slot(self) -> None:
        reply = QMessageBox.question(
            self,
            "Clear slot",
            f"Detach flow '{self._flow.name}' from this tile?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_slot()

    def _on_export_flow(self) -> None:
        if self._flow is None:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export Flow",
            f"{self._flow.name}.json",
            "JSON Files (*.json)",
        )
        if dest:
            try:
                export_flow(self._flow.id, dest)
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def _start_run(self, paths: List[str]) -> None:
        """Called when images are dropped.  Opens mode picker if >1 image."""
        if self._flow is None:
            self._open_flow_picker()
            return

        if len(paths) > 1:
            from app.flow_run_dialog import FlowRunDialog
            dlg = FlowRunDialog(flow=self._flow, image_paths=paths, parent=self)
            if not dlg.exec():
                return
            mode = dlg.selected_mode()
        else:
            mode = "per_image"

        if self._build_processor_fn is None:
            QMessageBox.warning(
                self, "Flow Tile",
                "This Flow Tile was created without a processor factory. "
                "The host application must pass build_processor_fn to FlowTile."
            )
            return
        self._engine = FlowEngine(
            build_processor_fn=self._build_processor_fn,
            parent=self,
        )
        self._engine.stepStarted.connect(self._on_step_started)
        self._engine.stepProgress.connect(self._on_step_progress)
        self._engine.flowFinished.connect(self._on_flow_finished)
        self._engine.flowError.connect(self._on_flow_error)

        self._running = True
        self._progress_value = 0
        self._status_text = f"Starting · {len(paths)} image(s)"
        self._show_progress(True)
        self.runStarted.emit()

        self._engine.run_flow(
            flow=self._flow,
            source_paths=paths,
            mode=mode,
        )

    def _on_step_started(self, step_idx: int, total_steps: int, tool_id: str) -> None:
        label = ""
        if self._flow:
            steps = self._flow.steps
            if 0 <= step_idx < len(steps):
                label = steps[step_idx].effective_label()
        self._status_text = f"Step {step_idx + 1}/{total_steps}: {label or tool_id}"
        self._status_label.setText(self._status_text)

    def _on_step_progress(self, step_idx: int, image_idx: int, pct: int) -> None:
        if self._flow:
            total_steps = len(self._flow.steps)
            overall = int((step_idx * 100 + pct) / max(total_steps, 1))
            self._progress_bar.setValue(overall)

    def _on_flow_finished(self, summary_json: str) -> None:
        self._running = False
        self._show_progress(False)
        self.runFinished.emit(summary_json)

        # Open cull dialog
        try:
            import json
            summary = json.loads(summary_json)
            from app.flow_cull_dialog import FlowCullDialog
            dlg = FlowCullDialog(summary=summary, parent=self)
            dlg.exec()
        except Exception as e:
            print(f"[flow] Could not open cull dialog: {e}")

    def _on_flow_error(self, err_msg: str) -> None:
        self._running = False
        self._show_progress(False)
        print(f"[flow] FlowTile error: {err_msg}")
        # Try host toast (MainWindow exposes self.toasts: ToastManager); fall back
        # to a modal if not reachable.
        shown = False
        try:
            w = self.window()
            toasts = getattr(w, "toasts", None) or getattr(w, "toast", None)
            if toasts is not None and hasattr(toasts, "show_toast"):
                toasts.show_toast(f"Flow error: {err_msg[:80]}", kind="error")
                shown = True
        except Exception:
            pass
        if not shown:
            QMessageBox.critical(self, "Flow Error", err_msg[:300])

    def _show_progress(self, visible: bool) -> None:
        self._progress_bar.setVisible(visible)
        self._status_label.setVisible(visible)
        if visible:
            self._progress_bar.setValue(0)
            self._status_label.setText(self._status_text)
        else:
            self._status_text = ""
        self.update()
