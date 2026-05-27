"""
In-app toast notifications.

Small floating cards that pop in the bottom-right of the main window when a
job finishes, errors, or hits a milestone. They stack vertically and fade
out automatically. Hover pauses the dismiss timer.

Usage:
    self.toasts = ToastManager(self)
    self.toasts.show_toast("Saved photo_x4.png", kind="success")
    self.toasts.show_toast("rembg failed: missing model", kind="error")
"""

from __future__ import annotations
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QGraphicsOpacityEffect, QWidget,
    QGraphicsDropShadowEffect,
)

from app import theme


KIND_COLORS = {
    "success": ("#1f3a2a", theme.EMBER_GOLD),
    "info":    ("#26303f", "#7DD3FC"),
    "error":   ("#3a1f23", theme.BRAND_RED),
    "warn":    ("#3a2f1f", theme.EMBER_ORANGE),
}

TOAST_MARGIN = 14
TOAST_GAP = 8
DISMISS_AFTER_MS = 4200


class Toast(QFrame):
    def __init__(self, message: str, kind: str = "success",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFrameShape(QFrame.NoFrame)
        bg, fg = KIND_COLORS.get(kind, KIND_COLORS["info"])
        self.setStyleSheet(
            f"background: {bg}; border: 1px solid {fg}; border-radius: 8px;"
        )

        # Drop shadow for the floating effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)

        icon = QLabel({"success": "\u2713", "info": "\u24d8",
                       "error": "\u2718", "warn": "\u26a0"}.get(kind, "\u24d8"))
        icon.setStyleSheet(
            f"color: {fg}; font-size: 16px; font-weight: 700;"
        )
        h.addWidget(icon)

        self.label = QLabel(message)
        self.label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; background: transparent; font-size: 12px;"
        )
        self.label.setWordWrap(True)
        h.addWidget(self.label, 1)

        # Opacity effect for fade
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.label.setGraphicsEffect(self._opacity)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(220)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)

        self._fade_out = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_out.setDuration(320)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self._on_faded_out)

        # Auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(DISMISS_AFTER_MS)
        self._dismiss_timer.timeout.connect(self.dismiss)

        self._on_dismissed_cb = None

    def show_animated(self):
        self._fade_in.start()
        self._dismiss_timer.start()

    def dismiss(self):
        if self._dismiss_timer.isActive():
            self._dismiss_timer.stop()
        self._fade_out.start()

    def _on_faded_out(self):
        if self._on_dismissed_cb is not None:
            self._on_dismissed_cb(self)

    def enterEvent(self, event):
        # Pause dismiss while hovered
        self._dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._dismiss_timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        # Click to dismiss
        if event.button() == Qt.LeftButton:
            self.dismiss()
        super().mousePressEvent(event)

    def set_on_dismissed(self, cb):
        self._on_dismissed_cb = cb


class ToastManager:
    def __init__(self, parent_widget: QWidget, max_visible: int = 4):
        self.parent = parent_widget
        self.max_visible = max_visible
        self._toasts: List[Toast] = []

    def show_toast(self, message: str, kind: str = "info"):
        toast = Toast(message, kind=kind, parent=self.parent)
        toast.adjustSize()
        # Cap width so very long messages wrap
        max_w = min(420, max(280, self.parent.width() // 3))
        toast.setMaximumWidth(max_w)
        toast.setMinimumWidth(min(280, max_w))
        toast.adjustSize()

        toast.set_on_dismissed(self._on_toast_dismissed)

        # Pop the oldest if too many
        if len(self._toasts) >= self.max_visible:
            oldest = self._toasts[0]
            oldest.dismiss()

        self._toasts.append(toast)
        self._reposition()
        toast.show()
        toast.show_animated()

    def _reposition(self):
        # Stack from bottom-right
        pw = self.parent.width()
        ph = self.parent.height()
        x_right = pw - TOAST_MARGIN
        y = ph - TOAST_MARGIN
        for toast in reversed(self._toasts):
            tw = toast.width()
            th = toast.height()
            y -= th
            toast.move(QPoint(x_right - tw, y))
            y -= TOAST_GAP

    def _on_toast_dismissed(self, toast: Toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
        toast.hide()
        toast.deleteLater()
        self._reposition()

    def reposition_on_resize(self):
        """Call from MainWindow.resizeEvent so toasts stay glued to bottom-right."""
        self._reposition()
