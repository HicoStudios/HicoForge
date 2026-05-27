"""
Drop-zone tile widget (Chunk 3).

Two visual states:
  - EmptyTile: a "+" placeholder shown in unassigned slots.
  - Tile: an assigned tool, with name/category/glyph, gear/clear buttons,
    drag-and-drop image acceptance, and a live progress badge.

Tile public methods used by the queue:
  - set_queue_state(active, pending, processed)
  - flash_progress(message)
  - flash_error(message)

Signals:
  - chooseRequested(slot)
  - clearRequested(slot)
  - settingsRequested(slot)
  - reassignRequested(slot)
  - filesDropped(slot, paths)
"""

from pathlib import Path
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import (
    QDragEnterEvent, QDragLeaveEvent, QDropEvent, QColor, QAction
)
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QGraphicsOpacityEffect, QStackedLayout, QWidget, QMenu
)

from app import theme
from processors.tool_registry import ToolDef, CATEGORY_COLOR


IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    ".avif", ".heic", ".heif", ".gif"
}


def _collect_image_files(paths: list[str], recursive: bool = True) -> list[Path]:
    """Given dropped paths (files and/or folders), return all image file paths."""
    out: list[Path] = []
    seen = set()
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            continue
        if p.is_file():
            if p.suffix.lower() in IMAGE_EXTS and p not in seen:
                out.append(p)
                seen.add(p)
        elif p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for child in it:
                if child.is_file() and child.suffix.lower() in IMAGE_EXTS and child not in seen:
                    out.append(child)
                    seen.add(child)
    return out


class EmptyTile(QFrame):
    chooseRequested = Signal(int)

    def __init__(self, slot_index: int, parent=None):
        super().__init__(parent)
        self.slot_index = slot_index
        self.setObjectName("TileEmpty")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(180, 130)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(6)
        v.addStretch(1)

        plus = QLabel("+")
        plus.setAlignment(Qt.AlignCenter)
        plus.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 30px; font-weight: 300; background: transparent;"
        )
        v.addWidget(plus)

        label = QLabel("Choose tool")
        label.setObjectName("TileEmptyLabel")
        label.setAlignment(Qt.AlignCenter)
        v.addWidget(label)

        hint = QLabel(f"SLOT {slot_index + 1}")
        hint.setObjectName("TileEmptyHint")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)

        v.addStretch(1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.chooseRequested.emit(self.slot_index)
        super().mousePressEvent(event)


class _Badge(QLabel):
    """Top-right floating count/status badge on a Tile."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(22)
        self.setMinimumWidth(40)
        self.setStyleSheet(
            f"background: {theme.EMBER_ORANGE}; color: white; "
            f"border-radius: 11px; padding: 0 10px; font-size: 11px; font-weight: 700;"
        )
        self.hide()

    def show_count(self, text: str, color: str = None):
        bg = color or theme.EMBER_ORANGE
        self.setStyleSheet(
            f"background: {bg}; color: white; border-radius: 11px; "
            f"padding: 0 10px; font-size: 11px; font-weight: 700;"
        )
        self.setText(text)
        self.adjustSize()
        self.show()


class Tile(QFrame):
    clearRequested = Signal(int)
    settingsRequested = Signal(int)
    filesDropped = Signal(int, list)
    reassignRequested = Signal(int)
    downloadRequested = Signal(int)         # user wants to fetch the model
    showLastOutputRequested = Signal(int)   # user wants to compare last result
    revealLastOutputRequested = Signal(int) # user wants to open output in Explorer

    def __init__(self, slot_index: int, tool: ToolDef, parent=None):
        super().__init__(parent)
        self.slot_index = slot_index
        self.tool = tool

        self.setObjectName("Tile")
        self.setMinimumSize(180, 130)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._pending = 0
        self._active = False
        self._processed = 0
        self._model_missing = False
        self._has_last_output = False
        self._idle_hint = ""

        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)

        # Top row
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        cat = QLabel(self.tool.category)
        cat.setObjectName("TileCategory")
        cat_color = CATEGORY_COLOR.get(self.tool.category, theme.EMBER_GOLD)
        cat.setStyleSheet(
            f"color: {cat_color}; font-size: 9px; font-weight: 700; "
            f"letter-spacing: 1.8px; background: transparent;"
        )
        top.addWidget(cat)
        top.addStretch(1)

        self.gear = QPushButton("⚙")
        self.gear.setCursor(Qt.PointingHandCursor)
        self.gear.setFixedSize(24, 22)
        self.gear.setToolTip("Tile settings")
        self.gear.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {theme.TEXT_DIM}; "
            f"font-size: 13px; padding: 0; }}"
            f"QPushButton:hover {{ color: {theme.EMBER_ORANGE}; }}"
        )
        self.gear.clicked.connect(lambda: self.settingsRequested.emit(self.slot_index))
        top.addWidget(self.gear)

        self.clear_btn = QPushButton("✕")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setFixedSize(24, 22)
        self.clear_btn.setToolTip("Clear slot")
        self.clear_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {theme.TEXT_DIM}; "
            f"font-size: 11px; padding: 0; }}"
            f"QPushButton:hover {{ color: {theme.BRAND_RED}; }}"
        )
        self.clear_btn.clicked.connect(lambda: self.clearRequested.emit(self.slot_index))
        top.addWidget(self.clear_btn)

        outer.addLayout(top)

        # Center: glyph + name + meta
        center = QVBoxLayout()
        center.setSpacing(2)
        center.addStretch(1)

        glyph = QLabel(self.tool.glyph)
        glyph.setAlignment(Qt.AlignCenter)
        glyph.setStyleSheet(
            f"color: {CATEGORY_COLOR.get(self.tool.category, theme.EMBER_ORANGE)}; "
            f"font-size: 30px; background: transparent;"
        )
        center.addWidget(glyph)

        name = QLabel(self.tool.name)
        name.setObjectName("TileName")
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        center.addWidget(name)

        meta_bits = []
        if self.tool.native_scale != 1:
            meta_bits.append(f"{self.tool.native_scale}× native")
        if self.tool.default_suffix:
            meta_bits.append(self.tool.default_suffix.lstrip("_"))
        meta_text = "  ·  ".join(meta_bits) if meta_bits else self.tool.processor_key
        self.meta = QLabel(meta_text)
        self.meta.setAlignment(Qt.AlignCenter)
        self.meta.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; background: transparent;"
        )
        center.addWidget(self.meta)

        center.addStretch(1)
        outer.addLayout(center, 1)

        # Bottom hint
        self.drop_hint = QLabel("Drop images here")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setStyleSheet(
            f"color: {theme.TEXT_DISABLED}; font-size: 9px; letter-spacing: 1.5px; "
            f"background: transparent;"
        )
        outer.addWidget(self.drop_hint)

        # Floating badge in top-right (overlaid via raise_)
        self.badge = _Badge(self)
        self.badge.move(self.width() - 60, 8)

    # Reposition badge on resize
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "badge"):
            self.badge.adjustSize()
            self.badge.move(self.width() - self.badge.width() - 10, 8)

    # ---- Public state setters ----
    def set_queue_state(self, active: bool, pending: int, processed: int):
        self._active = active
        self._pending = pending
        self._processed = processed
        self._refresh_badge()

    def set_model_missing(self, missing: bool):
        """Toggle the yellow 'Model missing' state. Affects badge + bottom hint."""
        if self._model_missing == missing:
            return
        self._model_missing = missing
        if missing:
            self.drop_hint.setText("Model missing — right-click to download")
            self.drop_hint.setStyleSheet(
                f"color: {theme.WARNING}; font-size: 9px; letter-spacing: 1px; "
                f"background: transparent;"
            )
        else:
            self._reset_drop_hint()
        self._refresh_badge()

    def set_has_last_output(self, has: bool):
        """Toggle whether a left-click should open the compare dialog."""
        self._has_last_output = has
        self.setCursor(Qt.PointingHandCursor if has else Qt.ArrowCursor)

    def flash_progress(self, message: str):
        self.drop_hint.setText(message)
        self.drop_hint.setStyleSheet(
            f"color: {theme.EMBER_GOLD}; font-size: 9px; letter-spacing: 1.5px; "
            f"background: transparent;"
        )

    def flash_done(self, output_name: str):
        self.drop_hint.setText(f"✓ Saved {output_name}")
        self.drop_hint.setStyleSheet(
            f"color: {theme.SUCCESS}; font-size: 9px; letter-spacing: 1px; "
            f"background: transparent;"
        )
        QTimer.singleShot(3500, self._reset_drop_hint)

    def flash_error(self, message: str):
        self.drop_hint.setText(f"⚠ {message[:60]}")
        self.drop_hint.setStyleSheet(
            f"color: {theme.BRAND_RED}; font-size: 9px; letter-spacing: 1px; "
            f"background: transparent;"
        )
        QTimer.singleShot(6000, self._reset_drop_hint)

    def _reset_drop_hint(self):
        text = self._idle_hint or "Drop images here"
        self.drop_hint.setText(text)
        self.drop_hint.setStyleSheet(
            f"color: {theme.TEXT_DISABLED}; font-size: 9px; letter-spacing: 1.5px; "
            f"background: transparent;"
        )

    def set_idle_hint(self, text: str):
        """Customize the idle drop-hint (e.g. '4x → PNG').

        Pass '' to revert to the default 'Drop images here'.
        """
        self._idle_hint = text or ""
        if not self._active and not self._model_missing and self._pending == 0:
            self._reset_drop_hint()

    def _refresh_badge(self):
        if self._active and self._pending > 0:
            self.badge.show_count(f"{self._pending}↻", theme.EMBER_ORANGE)
        elif self._active:
            self.badge.show_count("●", theme.EMBER_ORANGE)
        elif self._pending > 0:
            self.badge.show_count(str(self._pending), theme.EMBER_GOLD)
        elif self._model_missing:
            self.badge.show_count("⚠ missing", theme.WARNING)
        elif self._processed > 0:
            self.badge.show_count(f"✓ {self._processed}", theme.SUCCESS)
            # Auto-fade the "done" badge after a moment
            QTimer.singleShot(4000, self._maybe_hide_badge)
        else:
            self.badge.hide()
        # Re-position after content change
        self.badge.adjustSize()
        self.badge.move(self.width() - self.badge.width() - 10, 8)

    def _maybe_hide_badge(self):
        if not self._active and self._pending == 0:
            self.badge.hide()

    # ---- Double-click to reassign ----
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.reassignRequested.emit(self.slot_index)
        super().mouseDoubleClickEvent(event)

    # ---- Single left-click on tile body → open last-output compare ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._has_last_output:
            # Ignore clicks on the buttons themselves (they handle their own signals)
            child = self.childAt(event.position().toPoint())
            if child is None or child is self.drop_hint or child is self.meta:
                self.showLastOutputRequested.emit(self.slot_index)
        super().mousePressEvent(event)

    # ---- Right-click context menu ----
    def _on_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.SURFACE_RAISED}; color: {theme.TEXT_PRIMARY}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 18px; }}"
            f"QMenu::item:selected {{ background: {theme.SURFACE_HOVER}; color: {theme.EMBER_ORANGE}; }}"
            f"QMenu::item:disabled {{ color: {theme.TEXT_DISABLED}; }}"
        )

        if self.tool.download_url and self.tool.model_filename:
            label = "Download model" if self._model_missing else "Re-download model"
            act_dl = QAction(label, menu)
            act_dl.triggered.connect(lambda: self.downloadRequested.emit(self.slot_index))
            menu.addAction(act_dl)
            menu.addSeparator()

        act_compare = QAction("View last result (before/after)", menu)
        act_compare.setEnabled(self._has_last_output)
        act_compare.triggered.connect(
            lambda: self.showLastOutputRequested.emit(self.slot_index)
        )
        menu.addAction(act_compare)

        act_reveal = QAction("Show last output in folder", menu)
        act_reveal.setEnabled(self._has_last_output)
        act_reveal.triggered.connect(
            lambda: self.revealLastOutputRequested.emit(self.slot_index)
        )
        menu.addAction(act_reveal)

        menu.addSeparator()
        act_settings = QAction("Tile settings…", menu)
        act_settings.triggered.connect(lambda: self.settingsRequested.emit(self.slot_index))
        menu.addAction(act_settings)

        act_change = QAction("Change tool…", menu)
        act_change.triggered.connect(lambda: self.reassignRequested.emit(self.slot_index))
        menu.addAction(act_change)

        act_clear = QAction("Clear slot", menu)
        act_clear.triggered.connect(lambda: self.clearRequested.emit(self.slot_index))
        menu.addAction(act_clear)

        menu.exec(self.mapToGlobal(pos))

    # ---- Drag and drop ----
    def dragEnterEvent(self, event: QDragEnterEvent):
        md = event.mimeData()
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            event.acceptProposedAction()
            self.setObjectName("TileActive")
            self.style().unpolish(self)
            self.style().polish(self)
            self.drop_hint.setText("Release to queue")
            self.drop_hint.setStyleSheet(
                f"color: {theme.EMBER_GOLD}; font-size: 9px; letter-spacing: 1.5px; "
                f"background: transparent;"
            )
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._restore_idle_visual()

    def dropEvent(self, event: QDropEvent):
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        files = _collect_image_files(urls, recursive=True)
        self._restore_idle_visual()
        if files:
            self.filesDropped.emit(self.slot_index, files)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _restore_idle_visual(self):
        self.setObjectName("Tile")
        self.style().unpolish(self)
        self.style().polish(self)
        self._reset_drop_hint()
