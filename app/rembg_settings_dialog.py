"""
Per-tile settings dialog for the Remove Background tool.

Pick which rembg model to use. Each model has different speed / quality /
size tradeoffs. First time you use a model, rembg downloads its ONNX
weights into ~/.u2net/.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QGroupBox,
    QDialogButtonBox, QWidget, QLineEdit,
)

from app import theme


# (display, key, blurb)
MODEL_CHOICES = [
    ("U^2-Net (general purpose)",        "u2net",
        "Default. ~170 MB. Good on most photos."),
    ("U^2-Net Lite (fast)",              "u2netp",
        "~4 MB. Fastest, lower quality."),
    ("U^2-Net Human",                    "u2net_human",
        "Tuned for people / portraits. ~170 MB."),
    ("IS-Net General (best general)",   "isnet",
        "Newer, often the best general-purpose result. ~170 MB."),
    ("IS-Net Anime",                    "isnet_anime",
        "For anime / illustrated art. ~170 MB."),
    ("Silueta (light)",                  "silueta",
        "~43 MB. Decent quality, smaller download."),
    ("BiRefNet General (heaviest)",      "birefnet",
        "Top quality, slowest. ~880 MB."),
]


class RembgSettingsDialog(QDialog):
    def __init__(self, tool, current: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tool = tool
        self._current = dict(current or {})
        self.setWindowTitle(f"{tool.name} \u2014 Settings")
        self.setModal(True)
        self.setMinimumWidth(480)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 14)
        v.setSpacing(12)

        info = QLabel(
            "Background removal model. The first run of each model "
            "downloads its weights into ~/.u2net/."
        )
        info.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        info.setWordWrap(True)
        v.addWidget(info)

        g = QGroupBox("Model")
        gl = QGridLayout(g)
        gl.setColumnStretch(1, 1)

        gl.addWidget(QLabel("Engine"), 0, 0)
        self.model_combo = QComboBox()
        for label, key, blurb in MODEL_CHOICES:
            self.model_combo.addItem(label, key)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        gl.addWidget(self.model_combo, 0, 1)

        self.blurb_label = QLabel("")
        self.blurb_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self.blurb_label.setWordWrap(True)
        gl.addWidget(self.blurb_label, 1, 0, 1, 2)

        v.addWidget(g)

        out_group = QGroupBox("Output")
        og = QGridLayout(out_group)
        og.setColumnStretch(1, 1)
        og.addWidget(QLabel("Suffix"), 0, 0)
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("(appended before extension, e.g. _cutout)")
        og.addWidget(self.suffix_edit, 0, 1)
        note = QLabel("Output is always PNG (transparent background).")
        note.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        og.addWidget(note, 1, 0, 1, 2)
        v.addWidget(out_group)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._populate_from_current()

    def _populate_from_current(self):
        c = self._current
        model = c.get("rembg_model") or "u2net"
        idx = self._index_for_value(self.model_combo, model)
        self.model_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.suffix_edit.setText(c.get("output_suffix", self.tool.default_suffix or "_cutout"))
        self._on_model_changed(self.model_combo.currentIndex())

    def _on_model_changed(self, idx):
        if 0 <= idx < len(MODEL_CHOICES):
            self.blurb_label.setText(MODEL_CHOICES[idx][2])

    def _index_for_value(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                return i
        return -1

    def result_settings(self) -> dict:
        out = dict(self._current)
        out["rembg_model"] = self.model_combo.currentData() or "u2net"
        out["output_suffix"] = self.suffix_edit.text().strip() or "_cutout"
        # Output format always PNG for cutouts
        out["target_format"] = "png"
        return out
