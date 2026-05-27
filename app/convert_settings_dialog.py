"""
Per-tile settings dialog for the Convert Format tile.

A small modal with:
  - Output format: PNG / JPG / WebP / TIFF
  - Quality slider (only enabled when JPG or WebP is selected)

Reads + writes a plain dict of overrides that the main window persists
in cfg['tile_settings'][slot_index].
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSlider, QGroupBox, QDialogButtonBox, QWidget,
)

from app import theme


FORMAT_LABELS = [
    ("PNG  \u2014 lossless, supports transparency", "png"),
    ("JPG  \u2014 small files, no transparency",     "jpg"),
    ("WebP \u2014 small + supports transparency",     "webp"),
    ("TIFF \u2014 archival, supports transparency",   "tiff"),
]


class ConvertSettingsDialog(QDialog):
    def __init__(self, tool_name: str, current: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"{tool_name} \u2014 Settings")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._current = dict(current or {})
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 14)
        v.setSpacing(14)

        # Format picker
        fmt_group = QGroupBox("Output format")
        fmt_layout = QVBoxLayout(fmt_group)
        self.fmt_combo = QComboBox()
        for label, value in FORMAT_LABELS:
            self.fmt_combo.addItem(label, value)
        # Restore selection
        current_fmt = (self._current.get("target_format") or "png").lower()
        for i in range(self.fmt_combo.count()):
            if self.fmt_combo.itemData(i) == current_fmt:
                self.fmt_combo.setCurrentIndex(i)
                break
        self.fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)
        fmt_layout.addWidget(self.fmt_combo)
        v.addWidget(fmt_group)

        # Quality slider
        self.qual_group = QGroupBox("Quality")
        ql = QVBoxLayout(self.qual_group)
        row = QHBoxLayout()
        self.qual_slider = QSlider(Qt.Horizontal)
        self.qual_slider.setRange(1, 100)
        self.qual_slider.setSingleStep(1)
        self.qual_slider.setPageStep(5)
        self.qual_label = QLabel("95")
        self.qual_label.setMinimumWidth(36)
        self.qual_slider.valueChanged.connect(
            lambda v: self.qual_label.setText(str(v))
        )
        row.addWidget(self.qual_slider, 1)
        row.addWidget(self.qual_label)
        ql.addLayout(row)
        self.qual_hint = QLabel(
            "Higher = better quality and larger files. "
            "Recommended: 90\u201395 for photos."
        )
        self.qual_hint.setWordWrap(True)
        self.qual_hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        ql.addWidget(self.qual_hint)
        v.addWidget(self.qual_group)

        # OK / Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        # Initial slider value
        self._on_fmt_changed(self.fmt_combo.currentIndex())

    def _on_fmt_changed(self, _index: int):
        fmt = self.fmt_combo.currentData()
        if fmt == "jpg":
            self.qual_group.setEnabled(True)
            self.qual_slider.setValue(int(self._current.get("jpg_quality", 95)))
        elif fmt == "webp":
            self.qual_group.setEnabled(True)
            self.qual_slider.setValue(int(self._current.get("webp_quality", 92)))
        else:
            # PNG / TIFF: lossless, no quality slider
            self.qual_group.setEnabled(False)
            self.qual_slider.setValue(100)

    def result_settings(self) -> dict:
        """Return the merged settings dict to persist."""
        out = dict(self._current)
        fmt = self.fmt_combo.currentData() or "png"
        out["target_format"] = fmt
        if fmt == "jpg":
            out["jpg_quality"] = int(self.qual_slider.value())
        elif fmt == "webp":
            out["webp_quality"] = int(self.qual_slider.value())
        return out
