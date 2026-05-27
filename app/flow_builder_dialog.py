"""
app/flow_builder_dialog.py
--------------------------
Modal dialogs for building and selecting Flows in HicoForge v1.1.0.

Contains two public dialog classes:

  FlowBuilderDialog
      Full editor for a single Flow.  Allows renaming, adding/removing/
      reordering steps, configuring per-step settings, choosing output mode.
      Returns the edited Flow on accept.

  FlowPickerDialog
      Compact list of existing saved flows.  Offers "Create new…" option.
      Used by FlowTile when no flow is assigned.

Step settings editing:
  Each step row has a gear (⚙) button.  Clicking it should open the
  existing per-tool settings dialog.  That dialog lives elsewhere in
  HicoForge and is not yet plumbed here.  See the TODO comment in
  _on_edit_step_settings().

Tool selection:
  "Add Step" opens a compact ToolPickerCompact dialog (defined below) that
  lists all tools from ALL_TOOLS grouped by category.
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional, Any

from PySide6.QtCore import Qt, QSize, QMimeData
from PySide6.QtGui import QFont, QColor, QIcon, QDrag
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QWidget,
    QCheckBox, QRadioButton, QButtonGroup, QGroupBox,
    QFileDialog, QMessageBox, QSizePolicy, QAbstractItemView,
    QScrollArea, QFrame, QSpacerItem, QComboBox, QSplitter,
    QDialogButtonBox,
)

from app import theme
from core.flow_engine import (
    Flow, FlowStep,
    OUTPUT_MODE_CUSTOM, OUTPUT_MODE_SOURCE_SUFFIX,
    OUTPUT_MODE_PER_RUN, OUTPUT_MODE_LAST_USED,
)
from core.flow_store import list_flows, new_flow_id
from processors.tool_registry import ALL_TOOLS, get_tool, tools_by_category, CATEGORY_ORDER

try:
    FLOW_ACCENT: str = theme.FLOW_ACCENT  # type: ignore[attr-defined]
except AttributeError:
    FLOW_ACCENT: str = theme.EMBER_ORANGE  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Step row widget
# ---------------------------------------------------------------------------

class StepRowWidget(QWidget):
    """A single row inside the step list showing one FlowStep."""

    def __init__(self, step: FlowStep, step_number: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._step = copy.deepcopy(step)
        self._step_number = step_number
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(8)

        # Step number badge
        num_label = QLabel(f"{self._step_number:02d}")
        num_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        num_label.setFixedWidth(22)
        num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num_label.setStyleSheet(
            f"color: #fff; background: {FLOW_ACCENT}; border-radius: 9px; padding: 2px 4px;"
        )
        layout.addWidget(num_label)

        # Tool name
        try:
            tool = get_tool(self._step.tool_id)
            tool_name = tool.name
        except Exception:
            tool_name = self._step.tool_id

        self._name_label = QLabel(tool_name)
        self._name_label.setFont(QFont("Segoe UI", 9))
        self._name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._name_label, 1)

        # "Edit before run" checkbox
        self._edit_checkbox = QCheckBox("Edit before run")
        self._edit_checkbox.setFont(QFont("Segoe UI", 8))
        self._edit_checkbox.setChecked(self._step.edit_before_run)
        self._edit_checkbox.setToolTip(
            "If checked, the settings dialog for this tool will open when the flow runs."
        )
        self._edit_checkbox.toggled.connect(self._on_edit_before_run_toggled)
        layout.addWidget(self._edit_checkbox)

        # Gear button: open per-tool settings
        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setFixedSize(28, 28)
        self._settings_btn.setToolTip("Edit step settings")
        self._settings_btn.clicked.connect(self._on_edit_step_settings)
        layout.addWidget(self._settings_btn)

        # Delete button
        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(28, 28)
        self._delete_btn.setToolTip("Remove this step")
        self._delete_btn.setStyleSheet("color: #c0392b;")
        layout.addWidget(self._delete_btn)  # connected externally by FlowBuilderDialog

        self.setLayout(layout)

    def get_step(self) -> FlowStep:
        """Return a copy of the FlowStep with current UI values."""
        step = copy.deepcopy(self._step)
        step.edit_before_run = self._edit_checkbox.isChecked()
        return step

    def delete_button(self) -> QPushButton:
        return self._delete_btn

    def _on_edit_before_run_toggled(self, checked: bool) -> None:
        self._step.edit_before_run = checked

    def _on_edit_step_settings(self) -> None:
        # TODO: wire to existing per-tool settings dialog
        # Expected call:  open_tool_settings_dialog(self._step.tool_id, self._step.settings_override)
        # On accept, merge returned dict into self._step.settings_override
        QMessageBox.information(
            self,
            "Settings",
            f"Per-tool settings dialog for '{self._step.tool_id}' not yet wired.\n"
            "Add call to the existing settings dialog here.",
        )


# ---------------------------------------------------------------------------
# FlowBuilderDialog
# ---------------------------------------------------------------------------

class FlowBuilderDialog(QDialog):
    """Full modal editor for a single Flow.

    Usage
    -----
    dlg = FlowBuilderDialog(flow=my_flow, parent=self)
    if dlg.exec():
        updated_flow = dlg.get_flow()
        save_flow(updated_flow)
    """

    def __init__(self, flow: Optional[Flow] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Flow Builder")
        self.setMinimumSize(580, 640)
        self.setModal(True)

        # Work on a deep copy so Cancel truly cancels
        if flow is None:
            self._flow = Flow(id=new_flow_id(), name="New Flow")
        else:
            import copy as _copy
            self._flow = Flow.from_dict(_copy.deepcopy(flow.to_dict()))

        self._build_ui()
        self._populate_from_flow()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # --- Flow name ---
        name_row = QHBoxLayout()
        name_label = QLabel("Flow name:")
        name_label.setFixedWidth(80)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("My Flow")
        self._name_edit.setFont(QFont("Segoe UI", 10))
        name_row.addWidget(name_label)
        name_row.addWidget(self._name_edit, 1)
        root.addLayout(name_row)

        # --- Steps group ---
        steps_group = QGroupBox("Steps (drag to reorder)")
        steps_layout = QVBoxLayout(steps_group)
        steps_layout.setSpacing(4)

        self._step_list = QListWidget()
        self._step_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._step_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._step_list.setSpacing(2)
        self._step_list.setMinimumHeight(220)
        steps_layout.addWidget(self._step_list)

        add_btn = QPushButton("+ Add Step")
        add_btn.setStyleSheet(f"background: {FLOW_ACCENT}; color: #fff; border-radius: 4px; padding: 4px 12px;")
        add_btn.clicked.connect(self._on_add_step)
        steps_layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        root.addWidget(steps_group)

        # --- Output mode group ---
        out_group = QGroupBox("Output destination")
        out_layout = QVBoxLayout(out_group)

        self._mode_group = QButtonGroup(self)
        self._radio_custom = QRadioButton("Custom folder")
        self._radio_source = QRadioButton("Source folder + suffix")
        self._radio_per_run = QRadioButton("Per-run timestamped subfolder (inside custom folder)")
        self._radio_last = QRadioButton("Last used folder")

        for rb in (self._radio_custom, self._radio_source, self._radio_per_run, self._radio_last):
            self._mode_group.addButton(rb)
            out_layout.addWidget(rb)

        # Custom folder row
        custom_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Choose folder…")
        self._folder_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_folder)
        custom_row.addWidget(QLabel("  Folder:"))
        custom_row.addWidget(self._folder_edit, 1)
        custom_row.addWidget(browse_btn)
        out_layout.addLayout(custom_row)

        # Suffix row
        suffix_row = QHBoxLayout()
        suffix_row.addWidget(QLabel("  Suffix:"))
        self._suffix_edit = QLineEdit("_flow_out")
        self._suffix_edit.setMaximumWidth(160)
        suffix_row.addWidget(self._suffix_edit)
        suffix_row.addStretch(1)
        out_layout.addLayout(suffix_row)

        self._radio_custom.toggled.connect(self._on_mode_changed)
        self._radio_source.toggled.connect(self._on_mode_changed)
        self._radio_per_run.toggled.connect(self._on_mode_changed)
        self._radio_last.toggled.connect(self._on_mode_changed)

        root.addWidget(out_group)

        # --- Dialog buttons ---
        btn_row = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        btn_row.rejected.connect(self.reject)
        btn_row.accepted.connect(self._on_save)

        # Extra "Save & Close" is the same as Save for a modal — just Accept
        save_close_btn = QPushButton("Save && Close")
        save_close_btn.clicked.connect(self._on_save)
        btn_row.addButton(save_close_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        root.addWidget(btn_row)

    # ------------------------------------------------------------------
    # Populate from flow
    # ------------------------------------------------------------------

    def _populate_from_flow(self) -> None:
        self._name_edit.setText(self._flow.name)

        # Steps
        self._step_list.clear()
        for idx, step in enumerate(self._flow.steps):
            self._add_step_row(step, idx + 1)

        # Output mode
        mode_map = {
            OUTPUT_MODE_CUSTOM: self._radio_custom,
            OUTPUT_MODE_SOURCE_SUFFIX: self._radio_source,
            OUTPUT_MODE_PER_RUN: self._radio_per_run,
            OUTPUT_MODE_LAST_USED: self._radio_last,
        }
        rb = mode_map.get(self._flow.output_mode, self._radio_source)
        rb.setChecked(True)

        self._folder_edit.setText(self._flow.output_folder)
        self._suffix_edit.setText(self._flow.output_suffix or "_flow_out")
        self._on_mode_changed()

    # ------------------------------------------------------------------
    # Step management
    # ------------------------------------------------------------------

    def _add_step_row(self, step: FlowStep, step_number: int) -> None:
        """Append a StepRowWidget to the QListWidget."""
        row_widget = StepRowWidget(step, step_number)
        row_widget.delete_button().clicked.connect(
            lambda: self._remove_step_row(row_widget)
        )

        item = QListWidgetItem(self._step_list)
        item.setSizeHint(row_widget.sizeHint())
        self._step_list.addItem(item)
        self._step_list.setItemWidget(item, row_widget)

    def _remove_step_row(self, row_widget: StepRowWidget) -> None:
        for i in range(self._step_list.count()):
            item = self._step_list.item(i)
            if self._step_list.itemWidget(item) is row_widget:
                self._step_list.takeItem(i)
                self._renumber_steps()
                return

    def _renumber_steps(self) -> None:
        """Update the step-number badges after add/remove/reorder."""
        # QListWidget internal move doesn't call us; we rely on reading order at save time.
        pass  # badges are cosmetic; correct numbers appear on next open

    def _collect_steps(self) -> List[FlowStep]:
        """Read the current step list in display order and return FlowStep list."""
        steps: List[FlowStep] = []
        for i in range(self._step_list.count()):
            item = self._step_list.item(i)
            widget = self._step_list.itemWidget(item)
            if isinstance(widget, StepRowWidget):
                steps.append(widget.get_step())
        return steps

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_add_step(self) -> None:
        dlg = ToolPickerCompact(parent=self)
        if dlg.exec():
            tool_id = dlg.selected_tool_id()
            if tool_id:
                step = FlowStep(tool_id=tool_id)
                num = self._step_list.count() + 1
                self._add_step_row(step, num)

    def _on_browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self._folder_edit.setText(folder)

    def _on_mode_changed(self) -> None:
        custom_active = self._radio_custom.isChecked() or self._radio_per_run.isChecked()
        suffix_active = self._radio_source.isChecked()
        self._folder_edit.setEnabled(custom_active)
        self._suffix_edit.setEnabled(suffix_active)

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Please enter a flow name.")
            return

        self._flow.name = name
        self._flow.steps = self._collect_steps()

        if self._radio_custom.isChecked():
            self._flow.output_mode = OUTPUT_MODE_CUSTOM
        elif self._radio_source.isChecked():
            self._flow.output_mode = OUTPUT_MODE_SOURCE_SUFFIX
        elif self._radio_per_run.isChecked():
            self._flow.output_mode = OUTPUT_MODE_PER_RUN
        else:
            self._flow.output_mode = OUTPUT_MODE_LAST_USED

        self._flow.output_folder = self._folder_edit.text().strip()
        self._flow.output_suffix = self._suffix_edit.text().strip() or "_flow_out"

        self.accept()

    # ------------------------------------------------------------------
    # Public getter
    # ------------------------------------------------------------------

    def get_flow(self) -> Flow:
        """Return the edited Flow after the dialog has been accepted."""
        return self._flow


# ---------------------------------------------------------------------------
# ToolPickerCompact  — small dialog to pick a tool for a new step
# ---------------------------------------------------------------------------

class ToolPickerCompact(QDialog):
    """Compact tool selection dialog for adding a step to a flow.

    Groups tools by category (using CATEGORY_ORDER from tool_registry).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Step — Choose Tool")
        self.setMinimumSize(340, 420)
        self.setModal(True)
        self._selected_tool_id: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Search bar
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search tools…")
        self._search_edit.textChanged.connect(self._filter_tools)
        root.addWidget(self._search_edit)

        # Tool list
        self._tool_list = QListWidget()
        self._tool_list.itemDoubleClicked.connect(self._on_accept)
        root.addWidget(self._tool_list, 1)

        self._populate_tool_list("")

        btn_row = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        btn_row.rejected.connect(self.reject)
        btn_row.accepted.connect(self._on_accept)
        root.addWidget(btn_row)

    def _populate_tool_list(self, filter_text: str) -> None:
        self._tool_list.clear()
        lower = filter_text.strip().lower()

        try:
            by_cat = tools_by_category()
            order = CATEGORY_ORDER
        except Exception:
            # Fallback: flat list
            by_cat = {"All": list(ALL_TOOLS)}
            order = ["All"]

        for cat in order:
            tools_in_cat = by_cat.get(cat, [])
            matching = [
                t for t in tools_in_cat
                if lower in t.name.lower() or lower in t.id.lower()
            ]
            if not matching:
                continue

            # Category header item
            header_item = QListWidgetItem(f"── {cat} ──")
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            header_item.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            header_item.setForeground(QColor(FLOW_ACCENT))
            self._tool_list.addItem(header_item)

            for tool in matching:
                item = QListWidgetItem(f"  {tool.name}")
                item.setData(Qt.ItemDataRole.UserRole, tool.id)
                self._tool_list.addItem(item)

    def _filter_tools(self, text: str) -> None:
        self._populate_tool_list(text)

    def _on_accept(self, _=None) -> None:
        current = self._tool_list.currentItem()
        if current and current.data(Qt.ItemDataRole.UserRole):
            self._selected_tool_id = current.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def selected_tool_id(self) -> Optional[str]:
        return self._selected_tool_id


# ---------------------------------------------------------------------------
# FlowPickerDialog  — choose an existing flow or request "create new"
# ---------------------------------------------------------------------------

class FlowPickerDialog(QDialog):
    """List of saved flows for assigning to a FlowTile.

    After exec():
      - selected_flow_id() returns an id if an existing flow was chosen
      - wants_new_flow() returns True if the user clicked "Create new flow…"
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a Flow")
        self.setMinimumSize(360, 400)
        self.setModal(True)
        self._selected_id: Optional[str] = None
        self._wants_new = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(QLabel("Select a saved flow or create a new one:"))

        self._flow_list = QListWidget()
        self._flow_list.itemDoubleClicked.connect(self._on_select)
        root.addWidget(self._flow_list, 1)

        flows = list_flows()
        for flow in flows:
            preview = flow.step_preview()
            text = f"{flow.name}  [{len(flow.steps)} steps]"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, flow.id)
            item.setToolTip(preview)
            self._flow_list.addItem(item)

        if not flows:
            empty = QListWidgetItem("No saved flows yet.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._flow_list.addItem(empty)

        # "Create new" button
        new_btn = QPushButton("+ Create new flow…")
        new_btn.setStyleSheet(f"color: {FLOW_ACCENT};")
        new_btn.clicked.connect(self._on_new_flow)
        root.addWidget(new_btn)

        btn_row = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        btn_row.rejected.connect(self.reject)
        btn_row.accepted.connect(self._on_select)
        root.addWidget(btn_row)

    def _on_select(self, _=None) -> None:
        item = self._flow_list.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole):
            self._selected_id = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _on_new_flow(self) -> None:
        self._wants_new = True
        self.accept()

    def selected_flow_id(self) -> Optional[str]:
        return self._selected_id

    def wants_new_flow(self) -> bool:
        return self._wants_new
