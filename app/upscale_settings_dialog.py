"""
Per-tile settings dialog for spandrel-based tools (upscale + cleanup).

  - Output scale  (1x, 1.5x, 2x, 3x, 4x, 6x, 8x) \u2014 non-native scales
    Lanczos-downsample from the model's native output
  - Output format (PNG / JPG / WebP / TIFF / preserve)
  - Quality slider (JPG/WebP only)
  - Filename suffix
  - Tile size for VRAM management (auto / 256 / 384 / 512 / 768 / 1024)
  - Preserve alpha checkbox

For pure cleanup tools (native_scale=1), the scale picker is locked to 1x.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QSlider, QGroupBox, QDialogButtonBox, QWidget, QLineEdit, QCheckBox,
)

from app import theme
from processors.tool_registry import ToolDef


SCALE_CHOICES = [
    ("1x  \u2014 no resize",                  1.0),
    ("1.5x",                                1.5),
    ("2x",                                  2.0),
    ("3x",                                  3.0),
    ("4x",                                  4.0),
    ("6x",                                  6.0),
    ("8x",                                  8.0),
]

FORMAT_CHOICES = [
    ("Preserve source format",                "preserve"),
    ("PNG  \u2014 lossless, alpha",                "png"),
    ("JPG  \u2014 small files, no alpha",          "jpg"),
    ("WebP \u2014 small + alpha",                  "webp"),
    ("TIFF \u2014 archival, alpha",                "tiff"),
]

TILE_CHOICES = [
    ("Auto (recommended)", 0),
    ("256 px",             256),
    ("384 px",             384),
    ("512 px",             512),
    ("768 px",             768),
    ("1024 px",           1024),
    ("1536 px",           1536),
]


class UpscaleSettingsDialog(QDialog):
    def __init__(self, tool: ToolDef, current: dict,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tool = tool
        self._current = dict(current or {})
        self.setWindowTitle(f"{tool.name} \u2014 Settings")
        self.setModal(True)
        self.setMinimumWidth(480)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 14)
        v.setSpacing(12)

        # --- Model info header
        info_lbl = QLabel(
            f"<b>{tool.name}</b> \u2014 native {tool.native_scale}\u00d7 "
            f"({tool.category.lower()})"
        )
        info_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        v.addWidget(info_lbl)

        # --- Output group
        out_group = QGroupBox("Output")
        out_layout = QGridLayout(out_group)
        out_layout.setColumnStretch(1, 1)
        row = 0

        # Scale
        out_layout.addWidget(QLabel("Scale"), row, 0)
        self.scale_combo = QComboBox()
        for label, value in SCALE_CHOICES:
            self.scale_combo.addItem(label, value)
        out_layout.addWidget(self.scale_combo, row, 1)
        row += 1

        # Format
        out_layout.addWidget(QLabel("Format"), row, 0)
        self.fmt_combo = QComboBox()
        for label, value in FORMAT_CHOICES:
            self.fmt_combo.addItem(label, value)
        self.fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)
        out_layout.addWidget(self.fmt_combo, row, 1)
        row += 1

        # Quality slider
        self.qual_label = QLabel("Quality")
        out_layout.addWidget(self.qual_label, row, 0)
        qrow = QHBoxLayout()
        self.qual_slider = QSlider(Qt.Horizontal)
        self.qual_slider.setRange(1, 100)
        self.qual_slider.setSingleStep(1)
        self.qual_slider.setPageStep(5)
        self.qual_value = QLabel("95")
        self.qual_value.setMinimumWidth(32)
        self.qual_slider.valueChanged.connect(
            lambda val: self.qual_value.setText(str(val))
        )
        qrow.addWidget(self.qual_slider, 1)
        qrow.addWidget(self.qual_value)
        qhost = QWidget()
        qhost.setLayout(qrow)
        out_layout.addWidget(qhost, row, 1)
        row += 1

        # Suffix
        out_layout.addWidget(QLabel("Suffix"), row, 0)
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText(
            "(appended before extension, e.g. _x4_UltraSharp)"
        )
        out_layout.addWidget(self.suffix_edit, row, 1)
        row += 1
        v.addWidget(out_group)

        # --- Performance group
        perf_group = QGroupBox("Performance")
        perf_layout = QGridLayout(perf_group)
        perf_layout.setColumnStretch(1, 1)
        prow = 0

        perf_layout.addWidget(QLabel("Tile size"), prow, 0)
        self.tile_combo = QComboBox()
        for label, value in TILE_CHOICES:
            self.tile_combo.addItem(label, value)
        perf_layout.addWidget(self.tile_combo, prow, 1)
        prow += 1

        tile_hint = QLabel(
            "Smaller = less VRAM, slower. Larger = faster, more VRAM. "
            "Auto picks based on free VRAM."
        )
        tile_hint.setWordWrap(True)
        tile_hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        perf_layout.addWidget(tile_hint, prow, 0, 1, 2)
        prow += 1

        self.alpha_check = QCheckBox("Preserve alpha channel (transparency)")
        perf_layout.addWidget(self.alpha_check, prow, 0, 1, 2)
        v.addWidget(perf_group)

        # OK / Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._populate_from_current()

    # ---- Populate from current settings ----
    def _populate_from_current(self):
        c = self._current
        # Scale
        scale = float(c.get("output_scale", self.tool.default_output_scale))
        idx = self._index_for_value(self.scale_combo, scale)
        self.scale_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # Format (fall back to tool.default_format)
        fmt = (c.get("target_format") or c.get("output_format")
               or self.tool.default_format or "preserve").lower()
        idx = self._index_for_value(self.fmt_combo, fmt)
        self.fmt_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # Suffix
        self.suffix_edit.setText(c.get("output_suffix", self.tool.default_suffix or ""))

        # Tile size
        tile_size = int(c.get("tile_size", 0))
        idx = self._index_for_value(self.tile_combo, tile_size)
        self.tile_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # Alpha
        self.alpha_check.setChecked(bool(c.get("preserve_alpha", True)))

        # Trigger format change to set initial quality slider state
        self._on_fmt_changed(self.fmt_combo.currentIndex())

    def _index_for_value(self, combo: QComboBox, value) -> int:
        for i in range(combo.count()):
            v = combo.itemData(i)
            if isinstance(v, float) and isinstance(value, (int, float)):
                if abs(v - float(value)) < 0.001:
                    return i
            elif v == value:
                return i
        return -1

    def _on_fmt_changed(self, _idx: int):
        fmt = self.fmt_combo.currentData()
        if fmt == "jpg":
            self._enable_quality(True)
            self.qual_slider.setValue(int(self._current.get("jpg_quality", 95)))
        elif fmt == "webp":
            self._enable_quality(True)
            self.qual_slider.setValue(int(self._current.get("webp_quality", 92)))
        else:
            self._enable_quality(False)
            self.qual_slider.setValue(100)

    def _enable_quality(self, on: bool):
        self.qual_label.setEnabled(on)
        self.qual_slider.setEnabled(on)
        self.qual_value.setEnabled(on)

    # ---- Output ----
    def result_settings(self) -> dict:
        out = dict(self._current)
        out["output_scale"] = float(self.scale_combo.currentData())
        fmt = self.fmt_combo.currentData() or "preserve"
        # Use target_format key for consistency with Convert dialog
        out["target_format"] = fmt
        out["output_suffix"] = self.suffix_edit.text().strip()
        out["tile_size"] = int(self.tile_combo.currentData())
        out["preserve_alpha"] = bool(self.alpha_check.isChecked())
        if fmt == "jpg":
            out["jpg_quality"] = int(self.qual_slider.value())
        elif fmt == "webp":
            out["webp_quality"] = int(self.qual_slider.value())
        return out
