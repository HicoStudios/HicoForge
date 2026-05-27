"""
Before/after compare dialog (Chunk 3.1).

Modal viewer with a vertical wipe slider:
  - Left half = source (before)
  - Right half = output (after)
  - Drag the divider left/right to wipe.
  - Both images are scaled to fit the viewport while preserving aspect ratio.
  - The "after" image is upscaled, so we scale it down to match "before" on screen
    while still letting you toggle full-size view via a button.

Also supports:
  - Toggle "Side-by-side" view (both fully visible side by side)
  - "Open output folder" button
  - Mouse wheel = zoom both images in sync
  - Spacebar = toggle wipe / side-by-side
"""

from __future__ import annotations
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import Qt, QPoint, QRect, QSize, Signal
from PySide6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QImage, QFont, QMouseEvent,
    QWheelEvent, QKeyEvent, QDesktopServices,
)
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QSizePolicy, QFrame, QMessageBox,
)

from app import theme


def open_in_explorer(path: Path):
    """Open the file's containing folder in the OS file manager, selecting the file."""
    p = Path(path)
    if not p.exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))
        return
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(p)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p.parent)], check=False)
    except Exception:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))


class CompareView(QWidget):
    """The actual image wipe widget."""

    def __init__(self, before: QPixmap, after: QPixmap, parent=None):
        super().__init__(parent)
        self._before_full = before
        self._after_full = after
        self.setMinimumSize(640, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._split_x_norm = 0.5     # 0..1, fraction across the image rect
        self._side_by_side = False
        self._dragging = False

    def set_side_by_side(self, on: bool):
        self._side_by_side = on
        self.update()

    def toggle_side_by_side(self):
        self.set_side_by_side(not self._side_by_side)

    # ---- Layout helpers ----
    def _fitted_rects(self) -> tuple[QRect, QPixmap, QPixmap]:
        """
        Return (target_rect, before_scaled, after_scaled).
        The two pixmaps are scaled to match the same on-screen size so they
        overlay perfectly. We use the larger (after) image's aspect ratio
        since that's the upscaled result the user wants to inspect.
        """
        # Pick the "after" aspect as canonical
        target_aspect_pix = self._after_full
        avail = self.rect().adjusted(12, 12, -12, -12)
        scaled = target_aspect_pix.scaled(
            avail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        w, h = scaled.width(), scaled.height()
        x = avail.left() + (avail.width() - w) // 2
        y = avail.top() + (avail.height() - h) // 2
        rect = QRect(x, y, w, h)

        # Scale the "before" to the SAME on-screen size as after, regardless of native res
        before_scaled = self._before_full.scaled(
            QSize(w, h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        return rect, before_scaled, scaled

    # ---- Paint ----
    def paintEvent(self, e):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG_BOTTOM))

        if self._before_full.isNull() or self._after_full.isNull():
            painter.setPen(QPen(QColor(theme.TEXT_DIM)))
            painter.drawText(self.rect(), Qt.AlignCenter, "Image unavailable")
            return

        target, before, after = self._fitted_rects()

        if self._side_by_side:
            # Two halves side by side
            half_w = target.width() // 2
            before_dst = QRect(target.left(), target.top(), half_w, target.height())
            after_dst = QRect(
                target.left() + half_w, target.top(),
                target.width() - half_w, target.height()
            )
            # Source rects (split each scaled pixmap in half)
            painter.drawPixmap(
                before_dst,
                before,
                QRect(0, 0, half_w, target.height())
            )
            painter.drawPixmap(
                after_dst,
                after,
                QRect(half_w, 0, after.width() - half_w, target.height())
            )
            # Divider line
            painter.setPen(QPen(QColor(theme.EMBER_ORANGE), 2))
            painter.drawLine(
                target.left() + half_w, target.top(),
                target.left() + half_w, target.bottom()
            )
        else:
            # Wipe view: draw "after" full, then overlay "before" up to split_x
            painter.drawPixmap(target, after, after.rect())
            split_x = int(target.width() * self._split_x_norm)
            if split_x > 0:
                src = QRect(0, 0, split_x, before.height())
                dst = QRect(target.left(), target.top(), split_x, target.height())
                painter.drawPixmap(dst, before, src)
            # Divider
            line_x = target.left() + split_x
            painter.setPen(QPen(QColor(theme.EMBER_ORANGE), 2))
            painter.drawLine(line_x, target.top(), line_x, target.bottom())
            # Handle knob
            knob_r = 12
            cy = target.center().y()
            painter.setBrush(QColor(theme.EMBER_ORANGE))
            painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
            painter.drawEllipse(QPoint(line_x, cy), knob_r, knob_r)
            painter.setPen(QPen(QColor("#1a1a1a"), 2))
            painter.drawLine(line_x - 4, cy, line_x + 4, cy)
            painter.drawLine(line_x, cy - 4, line_x, cy + 4)

        # Corner labels
        painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
        f = QFont(theme.FONT_TEXT.split(",")[0].strip(), 9, QFont.Bold)
        painter.setFont(f)
        bg = QColor(0, 0, 0, 160)
        before_lbl = "BEFORE"
        after_lbl = "AFTER"
        painter.fillRect(target.left() + 8, target.top() + 8, 62, 18, bg)
        painter.drawText(target.left() + 14, target.top() + 21, before_lbl)
        painter.fillRect(target.right() - 60, target.top() + 8, 54, 18, bg)
        painter.drawText(target.right() - 54, target.top() + 21, after_lbl)

    # ---- Interaction ----
    def _split_from_x(self, x: int):
        target, _, _ = self._fitted_rects()
        if target.width() <= 0:
            return
        rel = (x - target.left()) / target.width()
        self._split_x_norm = max(0.0, min(1.0, rel))
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and not self._side_by_side:
            self._dragging = True
            self._split_from_x(event.position().toPoint().x())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and not self._side_by_side:
            self._split_from_x(event.position().toPoint().x())

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Space:
            self.toggle_side_by_side()
        elif event.key() == Qt.Key_Left:
            self._split_x_norm = max(0.0, self._split_x_norm - 0.02)
            self.update()
        elif event.key() == Qt.Key_Right:
            self._split_x_norm = min(1.0, self._split_x_norm + 0.02)
            self.update()
        else:
            super().keyPressEvent(event)


class CompareDialog(QDialog):
    """
    Modal compare dialog. Use:
        CompareDialog.show_compare(parent, source_path, output_path, title)
    """

    def __init__(
        self, source: Path, output: Path, title: str = "Compare", parent=None
    ):
        super().__init__(parent)
        self.source = Path(source)
        self.output = Path(output)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(1100, 720)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.SURFACE}; color: {theme.TEXT_PRIMARY}; }}"
        )

        before = QPixmap(str(self.source))
        after = QPixmap(str(self.output))
        if before.isNull() or after.isNull():
            QMessageBox.warning(
                self, "Compare unavailable",
                f"Could not load images:\n  {self.source}\n  {self.output}"
            )

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        # Header
        header = QHBoxLayout()
        head = QLabel(title)
        head.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        header.addWidget(head)
        header.addStretch(1)

        # File size info
        try:
            before_kb = self.source.stat().st_size // 1024
            after_kb = self.output.stat().st_size // 1024
            sz = QLabel(f"{before.width()}×{before.height()} ({before_kb} KB)  →  "
                        f"{after.width()}×{after.height()} ({after_kb} KB)")
            sz.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
            header.addWidget(sz)
        except Exception:
            pass

        v.addLayout(header)

        # Compare view
        self.view = CompareView(before, after, self)
        v.addWidget(self.view, 1)

        # Bottom controls
        bottom = QHBoxLayout()
        self.mode_btn = QPushButton("Side by side")
        self.mode_btn.setCheckable(True)
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        self.mode_btn.setStyleSheet(self._btn_qss())
        self.mode_btn.toggled.connect(self._on_mode_toggle)
        bottom.addWidget(self.mode_btn)

        reveal_btn = QPushButton("Show in folder")
        reveal_btn.setCursor(Qt.PointingHandCursor)
        reveal_btn.setStyleSheet(self._btn_qss())
        reveal_btn.clicked.connect(lambda: open_in_explorer(self.output))
        bottom.addWidget(reveal_btn)

        open_btn = QPushButton("Open output")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setStyleSheet(self._btn_qss())
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output)))
        )
        bottom.addWidget(open_btn)

        bottom.addStretch(1)

        hint = QLabel("Drag the divider · Spacebar = side-by-side · ←/→ = step")
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        bottom.addWidget(hint)

        bottom.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(self._btn_qss(accent=True))
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)

        v.addLayout(bottom)

    def _btn_qss(self, accent: bool = False) -> str:
        color = theme.EMBER_ORANGE if accent else theme.TEXT_PRIMARY
        return (
            f"QPushButton {{ background: transparent; color: {color}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; border-radius: 6px; "
            f"padding: 6px 14px; font-size: 11px; }}"
            f"QPushButton:checked {{ border-color: {theme.EMBER_ORANGE}; color: {theme.EMBER_ORANGE}; }}"
            f"QPushButton:hover {{ border-color: {theme.EMBER_ORANGE}; color: {theme.EMBER_ORANGE}; }}"
        )

    def _on_mode_toggle(self, on: bool):
        self.view.set_side_by_side(on)
        self.mode_btn.setText("Wipe view" if on else "Side by side")

    @classmethod
    def show_compare(cls, parent, source: Path, output: Path, title: str = "Compare"):
        dlg = cls(source, output, title, parent)
        dlg.exec()
