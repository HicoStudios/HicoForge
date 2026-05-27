"""
Grid picker — top toolbar component that lets the user choose how many
tool slots are visible. Click 1 / 2 / 4 / 6 / 8 / 12 / All.

Emits `gridChanged(int)` where int is the chosen tile count
(or -1 for "All" mode, meaning "show every registered tool, scrollable").

Also hosts the preset dropdown (Save current / Load saved / Manage).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QComboBox, QButtonGroup,
    QSpacerItem, QSizePolicy
)

from app import theme


GRID_SIZES = [1, 2, 4, 6, 8, 12]  # plus "All"


class GridPicker(QWidget):
    gridChanged = Signal(int)        # int = tile count, -1 for All
    presetSelected = Signal(str)     # preset name (or "" for none)
    presetSaveRequested = Signal()   # user clicked Save Preset
    presetManageRequested = Signal()  # user clicked Manage

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GridPicker")
        self._active_grid = 4  # default
        self._build_ui()

    def _build_ui(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        label = QLabel("GRID")
        label.setObjectName("GridPickerLabel")
        row.addWidget(label)

        # Grid size buttons
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._size_buttons = {}

        for size in GRID_SIZES:
            btn = QPushButton(str(size))
            btn.setObjectName("GridBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked, s=size: self._set_grid(s))
            self._btn_group.addButton(btn)
            self._size_buttons[size] = btn
            row.addWidget(btn)

        all_btn = QPushButton("All")
        all_btn.setObjectName("GridBtn")
        all_btn.setCheckable(True)
        all_btn.setCursor(Qt.PointingHandCursor)
        all_btn.clicked.connect(lambda: self._set_grid(-1))
        self._btn_group.addButton(all_btn)
        self._size_buttons[-1] = all_btn
        row.addWidget(all_btn)

        # Default selection
        self._size_buttons[self._active_grid].setChecked(True)

        # Spacer
        row.addItem(QSpacerItem(20, 1, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Preset combo
        preset_label = QLabel("PRESET")
        preset_label.setObjectName("GridPickerLabel")
        row.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("PresetCombo")
        self.preset_combo.setCursor(Qt.PointingHandCursor)
        self.preset_combo.addItem("— No preset —", userData="")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        row.addWidget(self.preset_combo)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("GhostBtn")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self.presetSaveRequested.emit)
        row.addWidget(save_btn)

        manage_btn = QPushButton("Manage")
        manage_btn.setObjectName("GhostBtn")
        manage_btn.setCursor(Qt.PointingHandCursor)
        manage_btn.clicked.connect(self.presetManageRequested.emit)
        row.addWidget(manage_btn)

    def _set_grid(self, size):
        self._active_grid = size
        self.gridChanged.emit(size)

    def _on_preset_changed(self, idx):
        name = self.preset_combo.itemData(idx) or ""
        self.presetSelected.emit(name)

    def current_grid(self) -> int:
        return self._active_grid

    def set_grid(self, size: int):
        """Programmatic selection (used when loading a preset)."""
        if size in self._size_buttons:
            self._size_buttons[size].setChecked(True)
            self._active_grid = size

    def load_preset_list(self, names: list[str], current: str = ""):
        """Refresh the preset dropdown items."""
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("— No preset —", userData="")
        for n in names:
            self.preset_combo.addItem(n, userData=n)
        if current:
            idx = self.preset_combo.findData(current)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)
