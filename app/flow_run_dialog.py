"""
app/flow_run_dialog.py
----------------------
FlowRunDialog — Mode-picker dialog for HicoForge v1.1.0 Flow Tiles.

Shown automatically when the user drops MORE THAN ONE image onto a Flow Tile.
Single-image drops bypass this dialog and always use per_image mode.

The dialog shows:
  • A read-only step preview so the user knows what flow they are running
  • Two radio buttons: image-by-image vs stage-by-stage, with plain-English
    explanations of each
  • A "Remember for this session" checkbox (suppresses the dialog on the next
    drop until the app is restarted)
  • OK / Cancel buttons

Callers should inspect selected_mode() after exec() returns Accepted.

Session memory is stored as a module-level variable (_SESSION_CHOICE) and is
reset each time the application starts.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QButtonGroup, QCheckBox, QGroupBox, QDialogButtonBox,
    QScrollArea, QWidget, QFrame,
)

from app import theme
from core.flow_engine import Flow

try:
    FLOW_ACCENT: str = theme.FLOW_ACCENT  # type: ignore[attr-defined]
except AttributeError:
    FLOW_ACCENT: str = theme.EMBER_ORANGE  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Session-level memory (reset on app restart)
# ---------------------------------------------------------------------------

_SESSION_CHOICE: Optional[str] = None   # "per_image" | "per_stage" | None


def clear_session_choice() -> None:
    """Reset the remembered mode (call on app startup if desired)."""
    global _SESSION_CHOICE
    _SESSION_CHOICE = None


# ---------------------------------------------------------------------------
# FlowRunDialog
# ---------------------------------------------------------------------------

class FlowRunDialog(QDialog):
    """Modal dialog for choosing per_image vs per_stage execution mode.

    Parameters
    ----------
    flow:
        The Flow about to be executed (used for step preview display).
    image_paths:
        The list of images that will be processed.
    parent:
        Optional parent widget.
    """

    def __init__(
        self,
        flow: Flow,
        image_paths: List[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Start Flow Run")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._flow = flow
        self._image_paths = image_paths
        self._mode: str = "per_image"
        self._build_ui()

        # If user has a remembered choice, pre-select and offer skip
        global _SESSION_CHOICE
        if _SESSION_CHOICE == "per_image":
            self._radio_image.setChecked(True)
        elif _SESSION_CHOICE == "per_stage":
            self._radio_stage.setChecked(True)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title
        title = QLabel(f'Run  "{self._flow.name}"')
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {FLOW_ACCENT};")
        root.addWidget(title)

        sub = QLabel(
            f"{len(self._image_paths)} image(s)  ·  {len(self._flow.steps)} step(s)"
        )
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        root.addWidget(sub)

        # Step preview
        if self._flow.steps:
            steps_group = QGroupBox("Steps in this flow")
            steps_layout = QVBoxLayout(steps_group)
            steps_layout.setSpacing(2)
            for i, step in enumerate(self._flow.steps):
                lbl = QLabel(f"  {i + 1:02d}. {step.effective_label()}")
                lbl.setFont(QFont("Segoe UI", 9))
                steps_layout.addWidget(lbl)
            root.addWidget(steps_group)

        # Image list preview (up to 5 filenames)
        if self._image_paths:
            img_group = QGroupBox("Images to process")
            img_layout = QVBoxLayout(img_group)
            img_layout.setSpacing(2)
            preview_paths = self._image_paths[:5]
            for p in preview_paths:
                lbl = QLabel(f"  • {Path(p).name}")
                lbl.setFont(QFont("Segoe UI", 9))
                img_layout.addWidget(lbl)
            if len(self._image_paths) > 5:
                more = QLabel(f"  … and {len(self._image_paths) - 5} more")
                more.setFont(QFont("Segoe UI", 9))
                more.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
                img_layout.addWidget(more)
            root.addWidget(img_group)

        # Mode selection
        mode_group = QGroupBox("Processing order")
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(8)

        self._radio_image = QRadioButton("Image-by-image")
        self._radio_image.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._radio_image.setChecked(True)
        mode_layout.addWidget(self._radio_image)

        img_desc = QLabel(
            "   Each image passes through ALL steps before the next image starts.\n"
            "   Best for long pipelines — you get results for image 1 soonest."
        )
        img_desc.setFont(QFont("Segoe UI", 8))
        img_desc.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        img_desc.setWordWrap(True)
        mode_layout.addWidget(img_desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        mode_layout.addWidget(sep)

        self._radio_stage = QRadioButton("Stage-by-stage")
        self._radio_stage.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        mode_layout.addWidget(self._radio_stage)

        stage_desc = QLabel(
            "   ALL images run through Step 1, then ALL through Step 2, etc.\n"
            "   Useful when a GPU-heavy step benefits from batching."
        )
        stage_desc.setFont(QFont("Segoe UI", 8))
        stage_desc.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        stage_desc.setWordWrap(True)
        mode_layout.addWidget(stage_desc)

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._radio_image)
        self._mode_group.addButton(self._radio_stage)

        root.addWidget(mode_group)

        # Remember choice checkbox
        self._remember_check = QCheckBox(
            "Remember my choice for this session (don't ask again until restart)"
        )
        self._remember_check.setFont(QFont("Segoe UI", 8))
        root.addWidget(self._remember_check)

        # Dialog buttons
        btn_row = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        btn_row.button(QDialogButtonBox.StandardButton.Ok).setText("Start Flow")
        btn_row.rejected.connect(self.reject)
        btn_row.accepted.connect(self._on_accept)
        root.addWidget(btn_row)

    # ------------------------------------------------------------------
    # Accept handler
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        self._mode = "per_image" if self._radio_image.isChecked() else "per_stage"

        if self._remember_check.isChecked():
            global _SESSION_CHOICE
            _SESSION_CHOICE = self._mode

        self.accept()

    # ------------------------------------------------------------------
    # Public getter
    # ------------------------------------------------------------------

    def selected_mode(self) -> str:
        """Return the chosen mode string: 'per_image' or 'per_stage'."""
        return self._mode


# ---------------------------------------------------------------------------
# Convenience helper used by FlowTile
# ---------------------------------------------------------------------------

def get_run_mode(
    flow: Flow,
    image_paths: List[str],
    parent: Optional[QWidget] = None,
) -> Optional[str]:
    """Determine the run mode, showing the dialog only when required.

    Returns
    -------
    'per_image' or 'per_stage' on success, or None if the user cancelled.

    Skips the dialog entirely for a single image (always returns 'per_image')
    and also skips when the user has a remembered session choice.
    """
    if len(image_paths) <= 1:
        return "per_image"

    global _SESSION_CHOICE
    if _SESSION_CHOICE is not None:
        return _SESSION_CHOICE

    dlg = FlowRunDialog(flow=flow, image_paths=image_paths, parent=parent)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.selected_mode()
    return None
