"""
Settings dialog for a fixed All-tab Flow tile.

Output paths come from global app settings unless
"Override global output settings" is enabled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QMessageBox,
    QGroupBox,
    QCheckBox,
)

from app.flow_builder_dialog import FlowBuilderDialog
from core.flow_engine import Flow, FlowStep
from core.flow_store import new_flow_id
from core.flow_tile_config import flow_from_tile, steps_from_tile
from core.global_output_config import effective_flow_tile_cfg, global_output_summary


class FlowTileSettingsDialog(QDialog):
    def __init__(
        self,
        tile_cfg: Dict[str, Any],
        app_cfg: Optional[dict] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Flow Tile Settings")
        self.setMinimumWidth(520)
        self._tile_cfg = dict(tile_cfg)
        self._app_cfg = app_cfg or {}
        self._install_root = Path(__file__).resolve().parent.parent
        self._steps: List[FlowStep] = list(steps_from_tile(self._tile_cfg))
        self._build_ui()
        self._sync_from_config()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(QLabel("Display name (tile label only)"))
        self._name_edit = QLineEdit()
        root.addWidget(self._name_edit)

        global_hint = QLabel("")
        global_hint.setWordWrap(True)
        self._global_hint = global_hint
        root.addWidget(global_hint)

        self._override_check = QCheckBox("Override global output settings for this flow")
        self._override_check.toggled.connect(self._on_override_toggled)
        root.addWidget(self._override_check)

        override_group = QGroupBox("Flow output overrides")
        og = QVBoxLayout(override_group)
        og.addWidget(QLabel("Project folder name"))
        self._folder_edit = QLineEdit()
        og.addWidget(self._folder_edit)
        og.addWidget(QLabel("Base name override (filenames only)"))
        self._base_name_edit = QLineEdit()
        og.addWidget(self._base_name_edit)
        og.addWidget(QLabel("Filename pattern"))
        self._pattern_edit = QLineEdit()
        og.addWidget(self._pattern_edit)
        self._override_group = override_group
        root.addWidget(override_group)

        steps_group = QGroupBox("Flow steps")
        steps_layout = QVBoxLayout(steps_group)
        self._steps_label = QLabel("No steps configured.")
        self._steps_label.setWordWrap(True)
        steps_layout.addWidget(self._steps_label)
        edit_btn = QPushButton("Edit Steps...")
        edit_btn.clicked.connect(self._edit_flow_steps)
        steps_layout.addWidget(edit_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(steps_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_save)
        root.addWidget(buttons)

    def _sync_from_config(self) -> None:
        self._name_edit.setText(str(self._tile_cfg.get("display_name") or ""))
        self._override_check.setChecked(bool(self._tile_cfg.get("override_global_output")))
        self._folder_edit.setText(str(self._tile_cfg.get("flow_folder_name") or ""))
        self._base_name_edit.setText(str(self._tile_cfg.get("base_name_override") or ""))
        self._pattern_edit.setText(
            str(self._tile_cfg.get("filename_pattern") or "{source_name}__r{run_id}__{step_name}")
        )
        self._global_hint.setText(
            "Global output: " + global_output_summary(self._app_cfg, self._install_root)
        )
        self._refresh_steps_label()
        self._on_override_toggled()

    def _on_override_toggled(self) -> None:
        on = self._override_check.isChecked()
        self._override_group.setEnabled(on)

    def _refresh_steps_label(self) -> None:
        if not self._steps:
            self._steps_label.setText("No steps configured. Click Edit Steps.")
            return
        lines = [f"{i + 1}. {s.effective_label()}" for i, s in enumerate(self._steps)]
        self._steps_label.setText("\n".join(lines))

    def _edit_flow_steps(self) -> None:
        flow = flow_from_tile(self._tile_cfg) or Flow(
            id=str(self._tile_cfg.get("flow_id") or "") or new_flow_id(),
            name=self._name_edit.text().strip() or "Flow",
            steps=[],
        )
        flow.steps = list(self._steps)
        dlg = FlowBuilderDialog(flow=flow, parent=self, steps_only=True)
        if dlg.exec():
            updated = dlg.get_flow()
            if not updated.steps:
                QMessageBox.warning(self, "Flow Tile", "Add at least one step.")
                return
            self._steps = list(updated.steps)
            self._tile_cfg["steps"] = [s.to_dict() for s in self._steps]
            if not str(self._tile_cfg.get("flow_id") or "").strip():
                self._tile_cfg["flow_id"] = updated.id
            self._refresh_steps_label()

    def _on_save(self) -> None:
        if not self._steps:
            QMessageBox.warning(self, "Flow Tile", "Configure at least one step (Edit Steps).")
            return

        self._tile_cfg["display_name"] = self._name_edit.text().strip() or "Flow"
        self._tile_cfg["override_global_output"] = bool(self._override_check.isChecked())
        if self._tile_cfg["override_global_output"]:
            self._tile_cfg["flow_folder_name"] = self._folder_edit.text().strip() or "Flow_1"
            self._tile_cfg["base_name_override"] = self._base_name_edit.text().strip()
            self._tile_cfg["filename_pattern"] = (
                self._pattern_edit.text().strip() or "{source_name}__r{run_id}__{step_name}"
            )
        self._tile_cfg["steps"] = [s.to_dict() for s in self._steps]
        if not str(self._tile_cfg.get("flow_id") or "").strip():
            self._tile_cfg["flow_id"] = new_flow_id()
        self.accept()

    def tile_config(self) -> Dict[str, Any]:
        return self._tile_cfg

    def effective_output_cfg(self) -> Dict[str, Any]:
        return effective_flow_tile_cfg(self._app_cfg, self._tile_cfg, self._install_root)
