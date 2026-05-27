"""
Per-tile settings dialog for the Resize utility.

Choose a target spec (1080p / 2K / 4K / 8K / Instagram square / custom max
dimension), output format, quality, and whether to allow upscaling.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QSlider, QGroupBox, QDialogButtonBox, QWidget, QLineEdit, QCheckBox,
    QSpinBox,
)

from app import theme


# (label, internal key)
TARGET_CHOICES = [
    ("1080p (1920 long edge)",          "max_1080"),
    ("1440p (2560 long edge)",          "max_1440"),
    ("2K  (2048 long edge)",            "max_2048"),
    ("4K  (3840 long edge)",            "max_3840"),
    ("8K  (7680 long edge)",            "max_7680"),
    ("Instagram square (1080x1080)",    "ig_square"),
    ("Custom max dimension\u2026",            "custom"),
]

FORMAT_CHOICES = [
    ("Preserve source format",          "preserve"),
    ("PNG  \u2014 lossless, alpha",          "png"),
    ("JPG  \u2014 small files, no alpha",    "jpg"),
    ("WebP \u2014 small + alpha",            "webp"),
    ("TIFF \u2014 archival, alpha",          "tiff"),
]


class ResizeSettingsDialog(QDialog):
    def __init__(self, tool, current: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tool = tool
        self._current = dict(current or {})
        self.setWindowTitle(f"{tool.name} \u2014 Settings")
        self.setModal(True)
        self.setMinimumWidth(460)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 14)
        v.setSpacing(12)

        info = QLabel(
            "Resize to a fixed target. Never upscales unless you opt in."
        )
        info.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        info.setWordWrap(True)
        v.addWidget(info)

        # --- Target spec ---
        spec_group = QGroupBox("Target")
        sg = QGridLayout(spec_group)
        sg.setColumnStretch(1, 1)

        sg.addWidget(QLabel("Spec"), 0, 0)
        self.target_combo = QComboBox()
        for label, key in TARGET_CHOICES:
            self.target_combo.addItem(label, key)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        sg.addWidget(self.target_combo, 0, 1)

        # Custom dim spin (only enabled for "custom")
        sg.addWidget(QLabel("Custom max"), 1, 0)
        self.custom_spin = QSpinBox()
        self.custom_spin.setRange(64, 16384)
        self.custom_spin.setSingleStep(64)
        self.custom_spin.setSuffix(" px")
        sg.addWidget(self.custom_spin, 1, 1)

        self.upscale_check = QCheckBox(
            "Allow upscaling (otherwise small images pass through unchanged)"
        )
        sg.addWidget(self.upscale_check, 2, 0, 1, 2)

        v.addWidget(spec_group)

        # --- Format / quality ---
        out_group = QGroupBox("Output")
        og = QGridLayout(out_group)
        og.setColumnStretch(1, 1)

        og.addWidget(QLabel("Format"), 0, 0)
        self.fmt_combo = QComboBox()
        for label, key in FORMAT_CHOICES:
            self.fmt_combo.addItem(label, key)
        self.fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)
        og.addWidget(self.fmt_combo, 0, 1)

        self.qual_label = QLabel("Quality")
        og.addWidget(self.qual_label, 1, 0)
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
        og.addWidget(qhost, 1, 1)

        og.addWidget(QLabel("Suffix"), 2, 0)
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("(spec tag is auto-appended)")
        og.addWidget(self.suffix_edit, 2, 1)

        v.addWidget(out_group)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._populate_from_current()

    def _populate_from_current(self):
        c = self._current
        # Target
        target = c.get("target") or (self.tool.default_settings or {}).get("target", "max_2048")
        idx = self._index_for_value(self.target_combo, target)
        self.target_combo.setCurrentIndex(idx if idx >= 0 else 2)
        # Custom dim
        self.custom_spin.setValue(int(c.get("custom_dim", 2048)))
        # Upscale
        self.upscale_check.setChecked(bool(c.get("allow_upscale", False)))
        # Format
        fmt = (c.get("target_format") or c.get("output_format")
               or self.tool.default_format or "preserve").lower()
        idx = self._index_for_value(self.fmt_combo, fmt)
        self.fmt_combo.setCurrentIndex(idx if idx >= 0 else 0)
        # Suffix
        self.suffix_edit.setText(c.get("output_suffix", self.tool.default_suffix or ""))

        self._on_target_changed(self.target_combo.currentIndex())
        self._on_fmt_changed(self.fmt_combo.currentIndex())

    def _index_for_value(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                return i
        return -1

    def _on_target_changed(self, _idx):
        is_custom = self.target_combo.currentData() == "custom"
        self.custom_spin.setEnabled(is_custom)

    def _on_fmt_changed(self, _idx):
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

    def result_settings(self) -> dict:
        out = dict(self._current)
        out["target"] = self.target_combo.currentData() or "max_2048"
        out["custom_dim"] = int(self.custom_spin.value())
        out["allow_upscale"] = bool(self.upscale_check.isChecked())
        fmt = self.fmt_combo.currentData() or "preserve"
        out["target_format"] = fmt
        out["output_suffix"] = self.suffix_edit.text().strip()
        if fmt == "jpg":
            out["jpg_quality"] = int(self.qual_slider.value())
        elif fmt == "webp":
            out["webp_quality"] = int(self.qual_slider.value())
        return out
