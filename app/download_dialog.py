"""
Model download dialog (Chunk 3.1).

Modal dialog shown when the user clicks "Download model" on a tile.
Wraps a ModelDownloadJob and displays a progress bar with bytes/speed/ETA.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QMessageBox,
)

from app import theme
from core.model_downloader import ModelDownloadJob
from processors.tool_registry import ToolDef


def _fmt_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


def _fmt_speed(bps: float) -> str:
    if bps <= 0:
        return ""
    return f"{_fmt_bytes(int(bps))}/s"


def _fmt_eta(done: int, total: int, bps: float) -> str:
    if total <= 0 or bps <= 0 or done >= total:
        return ""
    secs = (total - done) / bps
    if secs > 3600:
        return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m left"
    if secs > 60:
        return f"{int(secs // 60)}m {int(secs % 60)}s left"
    return f"{int(secs)}s left"


class DownloadDialog(QDialog):
    """
    Modal download dialog for a single model file.

    Use:
        ok = DownloadDialog.run(parent, tool, models_folder)
        # returns True on success, False on cancel/error
    """

    def __init__(self, tool: ToolDef, models_folder: Path, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.models_folder = Path(models_folder)
        self.dest = self.models_folder / (tool.model_filename or "")
        self.job: Optional[ModelDownloadJob] = None
        self._success = False
        self._closed = False

        self.setWindowTitle(f"Download {tool.name}")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.SURFACE}; color: {theme.TEXT_PRIMARY}; }}"
        )

        self._build_ui()
        # Start automatically after a short delay so the window paints first.
        QTimer.singleShot(150, self._start_download)

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(10)

        title = QLabel(f"Downloading {self.tool.name}")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 15px; font-weight: 600;"
        )
        v.addWidget(title)

        fn = QLabel(f"File: {self.tool.model_filename}")
        fn.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        v.addWidget(fn)

        dest_lbl = QLabel(f"Saving to: {self.dest.parent}")
        dest_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        dest_lbl.setWordWrap(True)
        v.addWidget(dest_lbl)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background: {theme.BORDER_SUBTLE}; max-height: 1px;")
        v.addWidget(sep)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate until first chunk
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {theme.SURFACE_RAISED}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; border-radius: 5px; }}"
            f"QProgressBar::chunk {{ background: {theme.EMBER_ORANGE}; border-radius: 5px; }}"
        )
        v.addWidget(self.progress)

        # Status row
        status_row = QHBoxLayout()
        self.bytes_lbl = QLabel("Connecting…")
        self.bytes_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        status_row.addWidget(self.bytes_lbl)
        status_row.addStretch(1)
        self.speed_lbl = QLabel("")
        self.speed_lbl.setStyleSheet(f"color: {theme.EMBER_GOLD}; font-size: 11px;")
        status_row.addWidget(self.speed_lbl)
        v.addLayout(status_row)

        self.eta_lbl = QLabel("")
        self.eta_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        v.addWidget(self.eta_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        if self.tool.info_url:
            info_btn = QPushButton("Model info")
            info_btn.setCursor(Qt.PointingHandCursor)
            info_btn.setStyleSheet(self._ghost_btn_qss())
            info_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(self.tool.info_url))
            )
            btn_row.addWidget(info_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet(self._ghost_btn_qss(accent_red=True))
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_btn)

        v.addLayout(btn_row)

    def _ghost_btn_qss(self, accent_red: bool = False) -> str:
        accent = theme.BRAND_RED if accent_red else theme.EMBER_ORANGE
        return (
            f"QPushButton {{ background: transparent; color: {theme.TEXT_PRIMARY}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; border-radius: 6px; "
            f"padding: 6px 14px; font-size: 11px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )

    # ---- Downloader hookup ----
    def _start_download(self):
        if not self.tool.download_url:
            self.bytes_lbl.setText("No download URL configured.")
            self.cancel_btn.setText("Close")
            return
        self.job = ModelDownloadJob(
            url=self.tool.download_url,
            dest_path=self.dest,
            expected_size_mb=self.tool.download_size_mb,
            sha256=self.tool.download_sha256,
        )
        self.job.signals.progress.connect(self._on_progress)
        self.job.signals.finished.connect(self._on_finished)
        self.job.signals.error.connect(self._on_error)
        self.job.signals.cancelled.connect(self._on_cancelled)
        self.job.start()

    def _on_progress(self, done: int, total: int, speed: float):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            pct = done / total * 100
            self.bytes_lbl.setText(
                f"{_fmt_bytes(done)} / {_fmt_bytes(total)}  ·  {pct:.1f}%"
            )
        else:
            self.bytes_lbl.setText(f"{_fmt_bytes(done)} downloaded")
        self.speed_lbl.setText(_fmt_speed(speed))
        self.eta_lbl.setText(_fmt_eta(done, total, speed))

    def _on_finished(self, path: str):
        self._success = True
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.bytes_lbl.setText(f"Saved {Path(path).name}")
        self.speed_lbl.setText("")
        self.eta_lbl.setText("Done.")
        self.cancel_btn.setText("Close")
        # Auto-close after a beat so the queue can pick up the now-present model
        QTimer.singleShot(900, self.accept)

    def _on_error(self, message: str):
        self.bytes_lbl.setText("Download failed")
        self.speed_lbl.setText("")
        self.eta_lbl.setText("")
        self.cancel_btn.setText("Close")
        QMessageBox.warning(self, "Download failed", message)
        self.reject()

    def _on_cancelled(self):
        self.bytes_lbl.setText("Cancelled")
        self.reject()

    def _on_cancel(self):
        if self._success:
            self.accept()
            return
        if self.job and self.job.is_running():
            self.job.cancel()
            self.bytes_lbl.setText("Cancelling…")
            self.cancel_btn.setEnabled(False)
        else:
            self.reject()

    def closeEvent(self, e):
        if self.job and self.job.is_running() and not self._success:
            self.job.cancel()
        super().closeEvent(e)

    @classmethod
    def run(cls, parent, tool: ToolDef, models_folder: Path) -> bool:
        if not tool.download_url:
            QMessageBox.information(
                parent, "No download available",
                f"{tool.name} doesn't have a built-in download URL configured.\n\n"
                f"Place {tool.model_filename} into:\n  {models_folder}"
            )
            return False
        if not tool.model_filename:
            return False
        dlg = cls(tool, models_folder, parent)
        dlg.exec()
        return dlg._success
