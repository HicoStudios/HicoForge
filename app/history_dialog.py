"""
History panel \u2014 the full on-disk job log.

Loaded on demand from core/job_history.py. Shows a sortable table:
  Timestamp | Tool | Source | Output | Status

Buttons:
  - Open output (reveal in Explorer)
  - Compare (open the before/after dialog if both files still exist)
  - Clear history (wipe the .jsonl)
"""

from __future__ import annotations
import time
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QDialogButtonBox, QWidget, QLabel, QHeaderView,
    QMessageBox,
)

from app import theme
from app.compare_dialog import CompareDialog, open_in_explorer
from core.job_history import JobHistory, JobRecord
from processors.tool_registry import get_tool


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return ""


class HistoryDialog(QDialog):
    def __init__(self, history: JobHistory, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._history = history
        self.setWindowTitle("HicoForge \u2014 History")
        self.setModal(True)
        self.resize(900, 540)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 12)
        v.setSpacing(10)

        info = QLabel(
            "Every job HicoForge has run, newest at the top. "
            "Persisted across launches in your config folder."
        )
        info.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        info.setWordWrap(True)
        v.addWidget(info)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["When", "Tool", "Source", "Output", "Status"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSortingEnabled(False)  # we sort manually (newest first)
        v.addWidget(self.table, 1)

        # Action row
        action_row = QHBoxLayout()
        self.reveal_btn = QPushButton("Reveal output")
        self.reveal_btn.setCursor(Qt.PointingHandCursor)
        self.reveal_btn.clicked.connect(self._on_reveal)
        action_row.addWidget(self.reveal_btn)

        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setCursor(Qt.PointingHandCursor)
        self.compare_btn.clicked.connect(self._on_compare)
        action_row.addWidget(self.compare_btn)

        action_row.addStretch(1)

        self.clear_btn = QPushButton("Clear history\u2026")
        self.clear_btn.setObjectName("GhostBtn")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear)
        action_row.addWidget(self.clear_btn)

        v.addLayout(action_row)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        # "Close" button uses RejectRole by default
        for b in btns.buttons():
            b.clicked.connect(self.accept)
        v.addWidget(btns)

        self._records: List[JobRecord] = []
        self._reload()

    def _reload(self):
        records = self._history.all_records()
        records.sort(key=lambda r: r.timestamp, reverse=True)
        self._records = records
        self.table.setRowCount(len(records))
        for row, rec in enumerate(records):
            tool = get_tool(rec.tool_id)
            tool_name = tool.name if tool else rec.tool_id
            cells = [
                _fmt_ts(rec.timestamp),
                tool_name,
                str(rec.source),
                str(rec.output),
                "OK" if rec.success else "Error",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if not rec.success and col == 4:
                    item.setForeground(QColor(theme.BRAND_RED))
                elif col == 4 and rec.success:
                    item.setForeground(QColor(theme.EMBER_GOLD))
                if col in (2, 3):
                    item.setToolTip(text)
                self.table.setItem(row, col, item)

    def _selected_record(self) -> Optional[JobRecord]:
        row = self.table.currentRow()
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def _on_reveal(self):
        rec = self._selected_record()
        if not rec:
            return
        if not rec.output.exists():
            QMessageBox.information(
                self, "File missing",
                f"The output file no longer exists:\n\n{rec.output}"
            )
            return
        open_in_explorer(rec.output)

    def _on_compare(self):
        rec = self._selected_record()
        if not rec:
            return
        if not (rec.source.exists() and rec.output.exists()):
            QMessageBox.information(
                self, "Files missing",
                "One or both files no longer exist on disk."
            )
            return
        tool = get_tool(rec.tool_id)
        title = f"{tool.name if tool else 'Result'} \u2014 {rec.source.name}"
        CompareDialog.show_compare(self, rec.source, rec.output, title)

    def _on_clear(self):
        resp = QMessageBox.question(
            self, "Clear history?",
            "This deletes the persistent history log on disk. "
            "Your image files are untouched. Proceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp == QMessageBox.Yes:
            self._history.clear_all()
            self._reload()
