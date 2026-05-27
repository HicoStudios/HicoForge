"""
Tool picker dialog — shown when the user clicks an empty slot (or double-clicks
a configured tile to reassign). Lets the user browse and search all registered
tools, grouped by category, and pick one for the slot.

API:
    ToolPickerDialog.pick(parent, slot_index) -> tool_id | None
"""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QGraphicsDropShadowEffect, QButtonGroup,
    QWidget
)

from app import theme
from processors.tool_registry import (
    ALL_TOOLS, CATEGORY_ORDER, CATEGORY_COLOR, ToolDef,
    search_tools, tools_by_category, get_tool
)


class _ToolRow(QFrame):
    """A single clickable row inside the picker showing one tool."""
    clicked = Signal(str)  # tool_id

    def __init__(self, tool: ToolDef, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("PickerRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(72)
        self.setStyleSheet(self._idle_qss())

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(14)

        # Glyph badge
        badge = QLabel(tool.glyph)
        badge.setFixedSize(46, 46)
        badge.setAlignment(Qt.AlignCenter)
        cat_color = CATEGORY_COLOR.get(tool.category, theme.EMBER_ORANGE)
        badge.setStyleSheet(
            f"background: {theme.SURFACE_RAISED}; border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: 10px; color: {cat_color}; font-size: 22px;"
        )
        h.addWidget(badge)

        # Text block
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.setContentsMargins(0, 0, 0, 0)

        name = QLabel(tool.name)
        name.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        top_row.addWidget(name)

        cat = QLabel(tool.category)
        cat.setStyleSheet(
            f"color: {cat_color}; font-size: 8px; font-weight: 700; letter-spacing: 1.5px; "
            f"background: transparent; padding-left: 4px;"
        )
        top_row.addWidget(cat)

        # Scale tag if interesting
        if tool.native_scale != 1:
            scale_tag = QLabel(f"{tool.native_scale}×")
            scale_tag.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; font-size: 9px; font-weight: 600; "
                f"background: {theme.SURFACE_RAISED}; border-radius: 4px; "
                f"padding: 1px 6px;"
            )
            top_row.addWidget(scale_tag)

        top_row.addStretch(1)
        text_col.addLayout(top_row)

        desc = QLabel(tool.description)
        desc.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        desc.setWordWrap(True)
        text_col.addWidget(desc)

        h.addLayout(text_col, 1)

        chevron = QLabel("›")
        chevron.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 18px; background: transparent;"
        )
        h.addWidget(chevron)

    def _idle_qss(self):
        return (
            f"QFrame#PickerRow {{ background: {theme.SURFACE}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; border-radius: 10px; }}"
            f"QFrame#PickerRow:hover {{ background: {theme.SURFACE_HOVER}; "
            f"border-color: {theme.EMBER_ORANGE}; }}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.tool.id)
        super().mousePressEvent(event)


class ToolPickerDialog(QDialog):
    """Modal-ish frameless picker that returns a tool_id when accepted."""

    def __init__(self, parent=None, slot_index: int = 0, current_tool_id: str | None = None):
        super().__init__(parent)
        self.slot_index = slot_index
        self.current_tool_id = current_tool_id
        self.selected_tool_id: str | None = None
        self._active_category: str | None = None  # None = All

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(640, 580)

        self._build_ui()
        self._populate(query="", category=None)

    # --- Build ---
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        shell = QFrame(self)
        shell.setObjectName("RootShell")
        shell.setStyleSheet(
            f"QFrame#RootShell {{ background: qlineargradient("
            f"x1:0, y1:0, x2:0.5, y2:1, stop:0 {theme.BG_TOP}, stop:1 {theme.BG_BOTTOM}); "
            f"border-radius: {theme.RADIUS_LG}px; border: 1px solid {theme.BORDER_SUBTLE}; }}"
        )
        # Soft shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 6)
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)

        v = QVBoxLayout(shell)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"Choose tool for slot {self.slot_index + 1}")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_DISPLAY}; "
            f"font-size: 16px; font-weight: 600; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch(1)

        close_btn = QPushButton("✕")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(28, 26)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {theme.TEXT_SECONDARY}; "
            f"font-size: 14px; }}"
            f"QPushButton:hover {{ color: {theme.BRAND_RED}; }}"
        )
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        v.addLayout(header)

        # Search box
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, category, or description…")
        self.search.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE_RAISED}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; border-radius: 8px; "
            f"padding: 9px 12px; color: {theme.TEXT_PRIMARY}; font-size: 12px; }}"
            f"QLineEdit:focus {{ border-color: {theme.EMBER_ORANGE}; }}"
        )
        self.search.textChanged.connect(self._on_search_changed)
        v.addWidget(self.search)

        # Category filter pills
        cat_row = QHBoxLayout()
        cat_row.setSpacing(6)
        self._cat_group = QButtonGroup(self)
        self._cat_group.setExclusive(True)

        all_btn = self._make_cat_button("All", None)
        all_btn.setChecked(True)
        cat_row.addWidget(all_btn)
        self._cat_group.addButton(all_btn)

        for cat in CATEGORY_ORDER:
            b = self._make_cat_button(cat, cat)
            cat_row.addWidget(b)
            self._cat_group.addButton(b)

        cat_row.addStretch(1)
        v.addLayout(cat_row)

        # Scroll area for results
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        v.addWidget(self.scroll, 1)

        # Footer
        footer = QHBoxLayout()
        self.footer_status = QLabel("")
        self.footer_status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; background: transparent;"
        )
        footer.addWidget(self.footer_status)
        footer.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("GhostBtn")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)

        v.addLayout(footer)

    def _make_cat_button(self, label: str, cat_value: str | None):
        b = QPushButton(label)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        accent = CATEGORY_COLOR.get(cat_value, theme.EMBER_ORANGE) if cat_value else theme.EMBER_ORANGE
        b.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: 6px; padding: 5px 12px; color: {theme.TEXT_SECONDARY}; "
            f"font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}"
            f"QPushButton:hover {{ color: {theme.TEXT_PRIMARY}; border-color: {accent}; }}"
            f"QPushButton:checked {{ background: {accent}; color: white; border-color: {accent}; }}"
        )
        b.clicked.connect(lambda: self._set_category(cat_value))
        return b

    # --- Populate / filter ---
    def _on_search_changed(self, text):
        self._populate(query=text, category=self._active_category)

    def _set_category(self, cat: str | None):
        self._active_category = cat
        self._populate(query=self.search.text(), category=cat)

    def _populate(self, query: str, category: str | None):
        # Find tools
        results = search_tools(query) if query else list(ALL_TOOLS)
        if category:
            results = [t for t in results if t.category == category]

        # Build a fresh container
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        if not results:
            empty = QLabel("No tools match your search.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: 12px; padding: 40px;"
            )
            layout.addWidget(empty)
        else:
            # Group by category for readability when not filtered to one
            if category is None and not query:
                grouped = {}
                for t in results:
                    grouped.setdefault(t.category, []).append(t)
                for cat in CATEGORY_ORDER:
                    items = grouped.get(cat, [])
                    if not items:
                        continue
                    header = QLabel(cat)
                    header.setStyleSheet(
                        f"color: {CATEGORY_COLOR.get(cat, theme.EMBER_GOLD)}; "
                        f"font-size: 10px; font-weight: 700; letter-spacing: 2px; "
                        f"background: transparent; padding: 8px 2px 2px 2px;"
                    )
                    layout.addWidget(header)
                    for t in items:
                        row = _ToolRow(t)
                        row.clicked.connect(self._on_tool_chosen)
                        layout.addWidget(row)
            else:
                for t in results:
                    row = _ToolRow(t)
                    row.clicked.connect(self._on_tool_chosen)
                    layout.addWidget(row)

        layout.addStretch(1)
        self.scroll.setWidget(container)

        self.footer_status.setText(
            f"{len(results)} tool{'s' if len(results) != 1 else ''} available"
        )

    def _on_tool_chosen(self, tool_id: str):
        self.selected_tool_id = tool_id
        self.accept()

    # --- Static convenience ---
    @staticmethod
    def pick(parent, slot_index: int, current_tool_id: str | None = None) -> str | None:
        dlg = ToolPickerDialog(parent, slot_index, current_tool_id)
        if dlg.exec() == QDialog.Accepted:
            return dlg.selected_tool_id
        return None

    # --- Drag the dialog by its body ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if hasattr(self, "_drag_pos") and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)
