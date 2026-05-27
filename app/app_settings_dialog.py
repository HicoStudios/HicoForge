"""
Global app settings (Chunk 7).

  - Models folder (where spandrel-compatible .pth/.safetensors live)
  - Central output folder (empty = save next to source)
  - Auto-unload idle minutes (model cache idle eviction)
  - Max concurrent jobs (only the worker thread count today; reserved)
  - Theme (placeholder \u2014 the app ships dark; future expansion)
  - Recursive folder drops (apply to nested folders)
"""

from typing import Optional
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QGroupBox, QDialogButtonBox, QWidget, QLineEdit, QSpinBox, QPushButton,
    QFileDialog, QCheckBox,
)

from app import theme


THEME_CHOICES = [
    ("Dark (default)", "dark"),
    ("Auto (follow system)", "auto"),
]


class AppSettingsDialog(QDialog):
    """Edit the persistent app-level config dict in place."""

    def __init__(self, cfg: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cfg = dict(cfg)
        self.setWindowTitle("HicoForge \u2014 Settings")
        self.setModal(True)
        self.setMinimumWidth(560)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 14)
        v.setSpacing(12)

        # --- Folders ---
        folders_group = QGroupBox("Folders")
        fg = QGridLayout(folders_group)
        fg.setColumnStretch(1, 1)

        # Models folder
        fg.addWidget(QLabel("Models folder"), 0, 0)
        models_row = QHBoxLayout()
        self.models_edit = QLineEdit()
        models_browse = QPushButton("Browse\u2026")
        models_browse.setCursor(Qt.PointingHandCursor)
        models_browse.clicked.connect(self._pick_models_folder)
        models_row.addWidget(self.models_edit, 1)
        models_row.addWidget(models_browse)
        host1 = QWidget()
        host1.setLayout(models_row)
        fg.addWidget(host1, 0, 1)

        hint1 = QLabel(
            "Where HicoForge looks for .pth / .safetensors model files. "
            "ComfyUI's upscale_models folder is a good choice."
        )
        hint1.setWordWrap(True)
        hint1.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        fg.addWidget(hint1, 1, 0, 1, 2)

        # Central output folder
        fg.addWidget(QLabel("Central output"), 2, 0)
        out_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("(empty = save next to each source image)")
        output_browse = QPushButton("Browse\u2026")
        output_browse.setCursor(Qt.PointingHandCursor)
        output_browse.clicked.connect(self._pick_output_folder)
        output_clear = QPushButton("Clear")
        output_clear.setCursor(Qt.PointingHandCursor)
        output_clear.clicked.connect(lambda: self.output_edit.setText(""))
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(output_browse)
        out_row.addWidget(output_clear)
        host2 = QWidget()
        host2.setLayout(out_row)
        fg.addWidget(host2, 2, 1)

        hint2 = QLabel(
            "When set, every output lands at "
            "<folder>/<tool>/<mirrored source path>/<file>."
        )
        hint2.setWordWrap(True)
        hint2.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        fg.addWidget(hint2, 3, 0, 1, 2)

        self.recursive_check = QCheckBox(
            "Recurse into subfolders when a folder is dropped"
        )
        fg.addWidget(self.recursive_check, 4, 0, 1, 2)

        v.addWidget(folders_group)

        # --- Performance ---
        perf_group = QGroupBox("Performance")
        pg = QGridLayout(perf_group)
        pg.setColumnStretch(1, 1)

        pg.addWidget(QLabel("Auto-unload idle models after"), 0, 0)
        self.unload_spin = QSpinBox()
        self.unload_spin.setRange(1, 120)
        self.unload_spin.setSuffix(" min")
        pg.addWidget(self.unload_spin, 0, 1)

        pg.addWidget(QLabel("Max concurrent jobs"), 1, 0)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 4)
        pg.addWidget(self.concurrency_spin, 1, 1)

        hint3 = QLabel(
            "Currently HicoForge runs one job at a time on the worker thread. "
            "This setting is reserved for a multi-job upgrade and stored now."
        )
        hint3.setWordWrap(True)
        hint3.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        pg.addWidget(hint3, 2, 0, 1, 2)

        v.addWidget(perf_group)

        # --- Appearance ---
        appearance_group = QGroupBox("Appearance")
        ag = QGridLayout(appearance_group)
        ag.setColumnStretch(1, 1)

        ag.addWidget(QLabel("Theme"), 0, 0)
        self.theme_combo = QComboBox()
        for label, key in THEME_CHOICES:
            self.theme_combo.addItem(label, key)
        ag.addWidget(self.theme_combo, 0, 1)

        hint4 = QLabel(
            "HicoForge ships dark. Theme changes take effect on next launch."
        )
        hint4.setWordWrap(True)
        hint4.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        ag.addWidget(hint4, 1, 0, 1, 2)

        v.addWidget(appearance_group)

        # --- Buttons ---
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._populate()

    # ---- Populate / browse ----
    def _populate(self):
        c = self._cfg
        self.models_edit.setText(str(c.get("models_folder", "") or ""))
        self.output_edit.setText(str(c.get("central_output_folder", "") or ""))
        self.recursive_check.setChecked(bool(c.get("recursive_folders", True)))
        self.unload_spin.setValue(int(c.get("auto_unload_minutes", 10)))
        self.concurrency_spin.setValue(int(c.get("max_concurrent_jobs", 1)))
        # Theme
        idx = 0
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == c.get("theme", "dark"):
                idx = i
                break
        self.theme_combo.setCurrentIndex(idx)

    def _pick_models_folder(self):
        current = self.models_edit.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose models folder", current
        )
        if chosen:
            self.models_edit.setText(chosen)

    def _pick_output_folder(self):
        current = self.output_edit.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose central output folder", current
        )
        if chosen:
            self.output_edit.setText(chosen)

    # ---- Output ----
    def result_settings(self) -> dict:
        """Return the patched config dict (caller merges into the real cfg)."""
        out = dict(self._cfg)
        out["models_folder"] = self.models_edit.text().strip()
        out["central_output_folder"] = self.output_edit.text().strip()
        out["recursive_folders"] = bool(self.recursive_check.isChecked())
        out["auto_unload_minutes"] = int(self.unload_spin.value())
        out["max_concurrent_jobs"] = int(self.concurrency_spin.value())
        out["theme"] = self.theme_combo.currentData() or "dark"
        return out
