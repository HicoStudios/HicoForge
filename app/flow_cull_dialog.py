"""
app/flow_cull_dialog.py
-----------------------
FlowCullDialog — post-run preview and cull modal for HicoForge v1.1.0.

Opened automatically by FlowTile after a flow run completes.  Displays:

  • A tab (or scroll section) per processed source image
  • Side-by-side thumbnails of each step's intermediate output
  • Per-thumbnail:
      ★  Star button — mark this intermediate as "kept" (visual only;
         no file operation)
      🗑  Trash button — mark for deletion (file is deleted on "Apply")
      ↑  Promote button — re-copy this intermediate as the _final alias
  • Bottom bar: "Apply trash" confirmation, "Open Output Folder", Close

No image-processing logic is performed here.  All operations are file
system copy/delete only.

The dialog receives the summary dict produced by FlowEngine.flowFinished,
which has the structure:
    {
        "flow_name": str,
        "image_results": [
            {
                "source": str,           # original source path
                "final": str,            # current _final path
                "intermediates": [str],  # ordered list of step output paths
            },
            ...
        ]
    }
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import Qt, QSize, QThread, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QIcon, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QScrollArea, QFrame, QSizePolicy,
    QDialogButtonBox, QMessageBox, QApplication,
)

from app import theme

try:
    FLOW_ACCENT: str = theme.FLOW_ACCENT  # type: ignore[attr-defined]
except AttributeError:
    FLOW_ACCENT: str = theme.EMBER_ORANGE  # type: ignore[assignment]

_THUMB_SIZE = QSize(160, 160)
_THUMB_STYLE_NORMAL = "border: 2px solid #444; border-radius: 4px;"
_THUMB_STYLE_STAR = "border: 2px solid #f1c40f; border-radius: 4px;"
_THUMB_STYLE_TRASH = "border: 2px solid #c0392b; border-radius: 4px; opacity: 0.5;"
_THUMB_STYLE_FINAL = f"border: 3px solid {FLOW_ACCENT}; border-radius: 4px;"


# ---------------------------------------------------------------------------
# Thumbnail card widget
# ---------------------------------------------------------------------------

class ThumbCard(QWidget):
    """Widget displaying one intermediate image output with action buttons."""

    def __init__(
        self,
        image_path: str,
        step_label: str,
        is_final: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._image_path = image_path
        self._step_label = step_label
        self._is_final = is_final
        self._starred = False
        self._trashed = False
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Thumbnail image
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(_THUMB_SIZE)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet(_THUMB_STYLE_FINAL if self._is_final else _THUMB_STYLE_NORMAL)
        self._load_thumbnail()
        layout.addWidget(self._thumb_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Step label
        step_lbl = QLabel(self._step_label)
        step_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(step_lbl)

        # Filename
        fname = Path(self._image_path).name
        fname_lbl = QLabel(fname)
        fname_lbl.setFont(QFont("Segoe UI", 7))
        fname_lbl.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        fname_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fname_lbl.setWordWrap(True)
        layout.addWidget(fname_lbl)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._star_btn = QPushButton("★")
        self._star_btn.setFixedSize(32, 28)
        self._star_btn.setToolTip("Mark as kept")
        self._star_btn.setCheckable(True)
        self._star_btn.toggled.connect(self._on_star_toggled)

        self._trash_btn = QPushButton("🗑")
        self._trash_btn.setFixedSize(32, 28)
        self._trash_btn.setToolTip("Mark for deletion")
        self._trash_btn.setCheckable(True)
        self._trash_btn.toggled.connect(self._on_trash_toggled)

        self._promote_btn = QPushButton("↑ Final")
        self._promote_btn.setFixedHeight(28)
        self._promote_btn.setToolTip("Promote this intermediate as the _final alias")
        self._promote_btn.clicked.connect(self._on_promote)

        btn_row.addWidget(self._star_btn)
        btn_row.addWidget(self._trash_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._promote_btn)
        layout.addLayout(btn_row)

        if self._is_final:
            final_badge = QLabel("FINAL")
            final_badge.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            final_badge.setStyleSheet(
                f"color: #fff; background: {FLOW_ACCENT}; border-radius: 6px; padding: 1px 6px;"
            )
            final_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(final_badge)

    # ------------------------------------------------------------------

    def _load_thumbnail(self) -> None:
        """Load and scale the image thumbnail; show placeholder on error."""
        p = Path(self._image_path)
        if not p.exists():
            self._thumb_label.setText("(missing)")
            self._thumb_label.setStyleSheet("color: #888; border: 1px dashed #555;")
            return
        px = QPixmap(str(p))
        if px.isNull():
            self._thumb_label.setText("(no preview)")
            self._thumb_label.setStyleSheet("color: #888; border: 1px dashed #555;")
        else:
            scaled = px.scaled(
                _THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._thumb_label.setPixmap(scaled)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_star_toggled(self, checked: bool) -> None:
        self._starred = checked
        if checked:
            self._trash_btn.setChecked(False)
            self._thumb_label.setStyleSheet(_THUMB_STYLE_STAR)
        else:
            self._thumb_label.setStyleSheet(
                _THUMB_STYLE_FINAL if self._is_final else _THUMB_STYLE_NORMAL
            )
        self._star_btn.setText("★" if checked else "☆")

    def _on_trash_toggled(self, checked: bool) -> None:
        self._trashed = checked
        if checked:
            self._star_btn.setChecked(False)
            self._thumb_label.setStyleSheet(_THUMB_STYLE_TRASH)
        else:
            self._thumb_label.setStyleSheet(
                _THUMB_STYLE_FINAL if self._is_final else _THUMB_STYLE_NORMAL
            )

    def _on_promote(self) -> None:
        """Re-copy this intermediate as the _final alias for its source image."""
        src = Path(self._image_path)
        if not src.exists():
            QMessageBox.warning(self.window(), "File missing", f"Cannot find:\n{src}")
            return
        # Derive the _final path from this file's location
        # Pattern: {stem}_step##_{toolid}{ext}  →  {original_stem}_final{ext}
        # We reconstruct by stripping the _step##_... suffix
        parts = src.stem.rsplit("_step", 1)
        if len(parts) == 2:
            original_stem = parts[0]
        else:
            original_stem = src.stem
        final_path = src.parent / f"{original_stem}_final{src.suffix}"
        try:
            shutil.copy2(str(src), str(final_path))
            QMessageBox.information(
                self.window(),
                "Promoted",
                f"Copied to:\n{final_path.name}",
            )
        except Exception as e:
            QMessageBox.critical(self.window(), "Error", str(e))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def image_path(self) -> str:
        return self._image_path

    @property
    def is_trashed(self) -> bool:
        return self._trashed

    @property
    def is_starred(self) -> bool:
        return self._starred


# ---------------------------------------------------------------------------
# Per-image panel
# ---------------------------------------------------------------------------

class ImageCullPanel(QWidget):
    """Horizontal strip of ThumbCards for one source image's intermediates."""

    def __init__(
        self,
        image_result: Dict,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._result = image_result
        self._cards: List[ThumbCard] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Source image label
        src_name = Path(self._result.get("source", "")).name
        header = QLabel(f"Source: {src_name}")
        header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        root.addWidget(header)

        # Scroll area for thumbnails
        scroll = QScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(_THUMB_SIZE.height() + 130)

        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setSpacing(10)
        h_layout.setContentsMargins(4, 4, 4, 4)
        h_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        intermediates: List[str] = self._result.get("intermediates", [])
        final_path: str = self._result.get("final", "")

        for i, path in enumerate(intermediates):
            step_label = f"Step {i + 1}"
            is_final = (path == final_path)
            card = ThumbCard(image_path=path, step_label=step_label, is_final=is_final)
            self._cards.append(card)
            h_layout.addWidget(card)

        # If _final differs from last intermediate, show it too
        if final_path and final_path not in intermediates:
            card = ThumbCard(image_path=final_path, step_label="Final", is_final=True)
            self._cards.append(card)
            h_layout.addWidget(card)

        if not intermediates and not final_path:
            no_out = QLabel("No outputs found for this image.")
            no_out.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
            h_layout.addWidget(no_out)

        h_layout.addStretch(1)
        container.setLayout(h_layout)
        scroll.setWidget(container)
        root.addWidget(scroll)

    def collect_trash(self) -> List[str]:
        """Return paths of cards marked for deletion."""
        return [c.image_path for c in self._cards if c.is_trashed]


# ---------------------------------------------------------------------------
# FlowCullDialog
# ---------------------------------------------------------------------------

class FlowCullDialog(QDialog):
    """Post-run cull dialog.

    Parameters
    ----------
    summary:
        The dict decoded from FlowEngine.flowFinished JSON signal.
    parent:
        Optional parent widget.
    """

    def __init__(self, summary: Dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Flow — Review & Cull")
        self.setMinimumSize(800, 540)
        self.setModal(True)
        self._summary = summary
        self._panels: List[ImageCullPanel] = []
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Header
        flow_name = self._summary.get("flow_name", "Flow")
        img_ok = self._summary.get("images_ok", 0)
        img_fail = self._summary.get("images_failed", 0)

        title = QLabel(f"Results — {flow_name}")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {FLOW_ACCENT};")
        root.addWidget(title)

        summary_lbl = QLabel(
            f"✔ {img_ok} image(s) completed   ✘ {img_fail} failed"
        )
        summary_lbl.setFont(QFont("Segoe UI", 9))
        summary_lbl.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        root.addWidget(summary_lbl)

        # Tabs per image (or scrollable if many)
        image_results: List[Dict] = self._summary.get("image_results", [])

        if not image_results:
            root.addWidget(QLabel("No image results to display."))
        elif len(image_results) <= 8:
            # Use tabs for a manageable count
            tabs = QTabWidget()
            for img_result in image_results:
                panel = ImageCullPanel(img_result)
                self._panels.append(panel)
                tab_name = Path(img_result.get("source", "?")).name[:24]
                tabs.addTab(panel, tab_name)
            root.addWidget(tabs, 1)
        else:
            # Scrollable list for large batches
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout(scroll_widget)
            scroll_layout.setSpacing(12)
            for img_result in image_results:
                panel = ImageCullPanel(img_result)
                self._panels.append(panel)
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                scroll_layout.addWidget(panel)
                scroll_layout.addWidget(sep)
            scroll_layout.addStretch(1)
            scroll.setWidget(scroll_widget)
            root.addWidget(scroll, 1)

        # Bottom action bar
        action_bar = QHBoxLayout()

        self._open_folder_btn = QPushButton("Open Output Folder")
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        action_bar.addWidget(self._open_folder_btn)

        action_bar.addStretch(1)

        self._apply_trash_btn = QPushButton("🗑 Apply Trash")
        self._apply_trash_btn.setStyleSheet("color: #c0392b;")
        self._apply_trash_btn.clicked.connect(self._on_apply_trash)
        action_bar.addWidget(self._apply_trash_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        action_bar.addWidget(close_btn)

        root.addLayout(action_bar)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_open_folder(self) -> None:
        """Open the output folder for the first image result in Explorer."""
        image_results = self._summary.get("image_results", [])
        folder = ""
        for ir in image_results:
            final = ir.get("final", "")
            if final and Path(final).parent.exists():
                folder = str(Path(final).parent)
                break
            intermediates = ir.get("intermediates", [])
            if intermediates and Path(intermediates[-1]).parent.exists():
                folder = str(Path(intermediates[-1]).parent)
                break

        if not folder:
            QMessageBox.information(self, "Folder", "Could not determine output folder.")
            return

        try:
            import subprocess
            subprocess.Popen(["explorer", folder])
        except Exception:
            try:
                os.startfile(folder)  # type: ignore[attr-defined]
            except Exception as e:
                QMessageBox.information(self, "Output Folder", folder)

    def _on_apply_trash(self) -> None:
        """Collect all trashed intermediates and delete them from disk."""
        to_delete: List[str] = []
        for panel in self._panels:
            to_delete.extend(panel.collect_trash())

        if not to_delete:
            QMessageBox.information(self, "Nothing to delete", "No intermediates are marked for deletion.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm deletion",
            f"Permanently delete {len(to_delete)} file(s) from disk?\n\n"
            + "\n".join(Path(p).name for p in to_delete[:8])
            + ("\n…" if len(to_delete) > 8 else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = 0
        errors: List[str] = []
        for path in to_delete:
            try:
                os.remove(path)
                deleted += 1
                print(f"[flow] Deleted intermediate: {path}")
            except Exception as e:
                errors.append(f"{Path(path).name}: {e}")
                print(f"[flow] Could not delete {path}: {e}")

        msg = f"Deleted {deleted} file(s)."
        if errors:
            msg += f"\n\nFailed ({len(errors)}):\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "Done", msg)
