"""
Footer status strip:
  [GPU name · VRAM bar · used/total]   [status message]   [queue: N pending]

Polls free VRAM every few seconds. Updates passively from job queue signals.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget, QSizePolicy

from app import theme
from core.gpu_info import GPUInfo, refresh_free_vram


class VRamBar(QWidget):
    """A thin horizontal bar showing used/total VRAM."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._used = 0
        self._total = 1
        self.setFixedHeight(6)
        self.setMinimumWidth(120)

    def set_values(self, used_mb: int, total_mb: int):
        self._used = max(0, used_mb)
        self._total = max(1, total_mb)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        h = self.height()
        # Track
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        # Fill
        ratio = min(1.0, self._used / max(1, self._total))
        fill_w = int(w * ratio)
        if ratio > 0.85:
            color = QColor(theme.BRAND_RED)
        elif ratio > 0.6:
            color = QColor(theme.EMBER_ORANGE)
        else:
            color = QColor(theme.EMBER_GOLD)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(0, 0, fill_w, h, h / 2, h / 2)
        p.end()


class _ClickableLabel(QLabel):
    clicked = Signal()
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class StatusBar(QFrame):
    outputFolderClicked = Signal()

    def __init__(self, gpu: GPUInfo, parent=None):
        super().__init__(parent)
        self._gpu = gpu
        self.setFixedHeight(38)
        self.setStyleSheet(
            f"background: transparent; border-top: 1px solid {theme.BORDER_SUBTLE};"
        )

        h = QHBoxLayout(self)
        h.setContentsMargins(18, 0, 18, 0)
        h.setSpacing(12)

        # GPU label
        self.gpu_label = QLabel(self._gpu.short_label())
        self.gpu_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 500;"
        )
        h.addWidget(self.gpu_label)

        # VRAM bar (only if CUDA)
        self.vbar = VRamBar()
        if not self._gpu.available:
            self.vbar.hide()
        h.addWidget(self.vbar)

        self.vram_text = QLabel("")
        self.vram_text.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px;"
        )
        h.addWidget(self.vram_text)

        h.addSpacing(20)

        # Center status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        h.addWidget(self.status_label, 1)

        # Output folder indicator (clickable)
        self.output_label = _ClickableLabel("Output: next to source")
        self.output_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; "
            f"text-decoration: underline; padding: 2px 6px;"
        )
        self.output_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.output_label.setToolTip("Click to set a central output folder")
        self.output_label.clicked.connect(self.outputFolderClicked.emit)
        h.addWidget(self.output_label)

        h.addSpacing(12)

        # Queue indicator
        self.queue_label = QLabel("Queue: empty")
        self.queue_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; font-weight: 500;"
        )
        h.addWidget(self.queue_label)

        # Periodic VRAM refresh
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_vram)
        self._timer.start(3000)
        self._refresh_vram()

    def set_status(self, msg: str):
        self.status_label.setText(msg)

    def set_output_folder(self, folder: str):
        """Display the central output folder, or 'next to source' when empty."""
        if folder and folder.strip():
            # Shorten long paths
            shown = folder
            if len(shown) > 40:
                shown = "…" + shown[-39:]
            self.output_label.setText(f"Output: {shown}")
            self.output_label.setToolTip(f"Central output folder:\n{folder}\n\nClick to change.")
        else:
            self.output_label.setText("Output: next to source")
            self.output_label.setToolTip("Click to set a central output folder")

    def set_queue(self, pending: int, processed: int):
        if pending == 0 and processed == 0:
            self.queue_label.setText("Queue: empty")
        elif pending == 0:
            self.queue_label.setText(f"Done · {processed} processed")
        else:
            self.queue_label.setText(f"Queue: {pending} pending · {processed} done")

    def _refresh_vram(self):
        if not self._gpu.available:
            self.vram_text.setText("")
            return
        refresh_free_vram(self._gpu)
        used = self._gpu.used_vram_mb
        total = self._gpu.total_vram_mb
        self.vbar.set_values(used, total)
        used_gb = used / 1024
        total_gb = total / 1024
        if total_gb >= 10:
            self.vram_text.setText(f"{used_gb:.1f} / {total_gb:.0f} GB")
        else:
            self.vram_text.setText(f"{used_gb:.1f} / {total_gb:.1f} GB")
