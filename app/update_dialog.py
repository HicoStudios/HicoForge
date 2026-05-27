"""
Update UI for HicoForge.

Components:
- UpdateToast: small non-modal toast in the bottom-right corner with
  "Update available — click to install" text. Auto-dismisses after 12s.
- UpdateDialog: modal with the release name, version, changelog (rendered
  markdown), and two buttons: "Install Now" / "Later".
- UpdateProgressDialog: shown during download with a progress bar.

The UI never blocks. All network work runs on a worker thread; results
are marshalled back to the GUI thread via Qt signals.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt,
    QObject,
    QTimer,
    Signal,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import QGuiApplication, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# Import paired with the file living in core/
from core.updater import (
    UpdateInfo,
    check_async,
    download_and_stage,
    launch_updater,
    current_version,
)


# ─────────────────────────────────────────────────────────────────────────────
# Toast
# ─────────────────────────────────────────────────────────────────────────────

class UpdateToast(QWidget):
    """
    Small floating notification in the bottom-right corner of the parent
    window. Click → opens the update dialog. Auto-dismisses after 12s.
    """

    clicked = Signal()

    def __init__(self, parent: QWidget, version: str) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Brand-aligned dark card with amber accent
        self.setStyleSheet(
            """
            QWidget#card {
                background: #1A1A1F;
                border: 1px solid #3A3A40;
                border-radius: 10px;
            }
            QLabel#title {
                color: #FFB347;
                font-weight: 600;
                font-size: 13px;
            }
            QLabel#body {
                color: #E8E8EA;
                font-size: 11px;
            }
            QPushButton {
                background: #FFB347;
                color: #1A1A1F;
                border: none;
                padding: 6px 14px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton:hover { background: #FFC56B; }
            """
        )

        card = QWidget(self)
        card.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)

        title = QLabel(f"Update available — v{version}")
        title.setObjectName("title")

        body = QLabel("Click to view changes and install.")
        body.setObjectName("body")
        body.setWordWrap(True)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        view_btn = QPushButton("View")
        dismiss_btn = QPushButton("Dismiss")
        dismiss_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888; }"
            "QPushButton:hover { color: #FFF; }"
        )
        btn_row.addStretch(1)
        btn_row.addWidget(dismiss_btn)
        btn_row.addWidget(view_btn)

        v.addWidget(title)
        v.addWidget(body)
        v.addLayout(btn_row)

        view_btn.clicked.connect(self._on_view)
        dismiss_btn.clicked.connect(self._dismiss)

        # Auto-dismiss after 12s
        QTimer.singleShot(12_000, self._dismiss)

        # Fade-in
        self._opacity_fx = QGraphicsOpacityEffect(self)
        self._opacity_fx.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_fx)
        self._fade = QPropertyAnimation(self._opacity_fx, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.resize(300, 92)

    def show_at_corner(self) -> None:
        """Position in the bottom-right of the parent window with margin."""
        parent = self.parentWidget()
        if parent is None:
            geo = QGuiApplication.primaryScreen().availableGeometry()
            x = geo.right() - self.width() - 24
            y = geo.bottom() - self.height() - 24
        else:
            p_geo = parent.geometry()
            x = p_geo.right() - self.width() - 24
            y = p_geo.bottom() - self.height() - 56
        self.move(x, y)
        self.show()
        self._fade.start()

    def _on_view(self) -> None:
        self.clicked.emit()
        self.close()

    def _dismiss(self) -> None:
        if not self.isVisible():
            return
        try:
            self.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Modal dialog with changelog
# ─────────────────────────────────────────────────────────────────────────────

class UpdateDialog(QDialog):
    """Modal dialog showing the changelog and prompting Install / Later."""

    def __init__(self, info: UpdateInfo, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(f"HicoForge — Update available (v{info.version})")
        self.setMinimumSize(560, 460)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        # Header
        header_lbl = QLabel(info.name or f"HicoForge v{info.version}")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header_lbl.setFont(header_font)
        v.addWidget(header_lbl)

        sub_lbl = QLabel(
            f"Currently installed: v{current_version()}    →    "
            f"New: v{info.version}"
        )
        sub_lbl.setStyleSheet("color: #888;")
        v.addWidget(sub_lbl)

        # Changelog (markdown -> rich text via QTextBrowser)
        self._changelog = QTextBrowser(self)
        self._changelog.setOpenExternalLinks(True)
        body_md = info.body or "_No changelog provided._"
        try:
            self._changelog.setMarkdown(body_md)
        except Exception:
            self._changelog.setPlainText(body_md)
        v.addWidget(self._changelog, 1)

        # Footer / buttons
        btns = QDialogButtonBox(self)
        install_btn = btns.addButton("Install Now", QDialogButtonBox.ButtonRole.AcceptRole)
        later_btn = btns.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        install_btn.setDefault(True)
        install_btn.clicked.connect(self.accept)
        later_btn.clicked.connect(self.reject)
        v.addWidget(btns)


# ─────────────────────────────────────────────────────────────────────────────
# Progress dialog (during download)
# ─────────────────────────────────────────────────────────────────────────────

class UpdateProgressDialog(QDialog):
    """Modal progress dialog shown while the zip downloads."""

    progress = Signal(int, int)  # downloaded, total

    def __init__(self, info: UpdateInfo, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(f"Downloading v{info.version}…")
        self.setMinimumWidth(420)
        self.setModal(True)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        self._lbl = QLabel("Starting download…")
        v.addWidget(self._lbl)

        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        v.addWidget(self._bar)

        self.progress.connect(self._on_progress)

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._bar.setValue(pct)
            self._lbl.setText(
                f"Downloaded {downloaded / 1_048_576:.1f} MB "
                f"of {total / 1_048_576:.1f} MB"
            )
        else:
            self._bar.setRange(0, 0)  # indeterminate
            self._lbl.setText(f"Downloaded {downloaded / 1_048_576:.1f} MB")


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class UpdateManager(QObject):
    """
    Coordinates: silent check -> toast -> dialog -> download -> hand-off.

    Hold an instance on the main window. Call check_silently() once on
    startup; the user can also trigger check_manually() from the Help
    menu, which surfaces "no update" / "you're on the latest" messages.
    """

    _update_found = Signal(object)   # UpdateInfo
    _no_update = Signal()
    _check_failed = Signal()

    def __init__(self, parent_window: QWidget) -> None:
        super().__init__(parent_window)
        self._window = parent_window
        self._toast: Optional[UpdateToast] = None
        self._manual_mode = False

        self._update_found.connect(self._on_update_found)
        self._no_update.connect(self._on_no_update)
        self._check_failed.connect(self._on_check_failed)

    # ── Entry points ────────────────────────────────────────────────────────

    def check_silently(self) -> None:
        """Background check; only surfaces UI if an update is found."""
        self._manual_mode = False
        check_async(self._async_done)

    def check_manually(self) -> None:
        """Triggered by Help → Check for Updates. Always surfaces a result."""
        self._manual_mode = True
        check_async(self._async_done)

    # ── Async glue ──────────────────────────────────────────────────────────

    def _async_done(self, info: Optional[UpdateInfo]) -> None:
        # Called on the worker thread. Marshal via signals.
        if info is None:
            # Could be: no update available OR check failed. We can't
            # distinguish reliably here; default to "no update" for the
            # manual case (less alarming) and stay quiet for silent.
            self._no_update.emit()
            return
        self._update_found.emit(info)

    # ── Signal handlers (GUI thread) ────────────────────────────────────────

    def _on_update_found(self, info: UpdateInfo) -> None:
        if self._manual_mode:
            # Manual: go straight to the dialog
            self._show_dialog(info)
        else:
            # Silent: toast first, dialog only on click
            self._toast = UpdateToast(self._window, info.version)
            self._toast.clicked.connect(lambda inf=info: self._show_dialog(inf))
            self._toast.show_at_corner()

    def _on_no_update(self) -> None:
        if self._manual_mode:
            QMessageBox.information(
                self._window,
                "HicoForge",
                f"You're on the latest version (v{current_version()}).",
            )

    def _on_check_failed(self) -> None:
        if self._manual_mode:
            QMessageBox.warning(
                self._window,
                "HicoForge",
                "Could not check for updates. Please check your internet "
                "connection and try again.",
            )

    # ── Dialog + download ───────────────────────────────────────────────────

    def _show_dialog(self, info: UpdateInfo) -> None:
        dlg = UpdateDialog(info, self._window)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._begin_download(info)

    def _begin_download(self, info: UpdateInfo) -> None:
        prog = UpdateProgressDialog(info, self._window)
        prog.show()

        result: dict = {"path": None, "err": None}

        def worker() -> None:
            try:
                path = download_and_stage(
                    info,
                    progress_cb=lambda d, t: prog.progress.emit(d, t),
                )
                result["path"] = path
            except Exception as exc:  # noqa: BLE001
                result["err"] = str(exc)

            # Schedule completion on GUI thread
            QTimer.singleShot(0, lambda: self._download_done(prog, info, result))

        threading.Thread(target=worker, daemon=True, name="UpdateDownloader").start()

    def _download_done(
        self,
        prog: UpdateProgressDialog,
        info: UpdateInfo,
        result: dict,
    ) -> None:
        prog.close()
        if result["err"]:
            QMessageBox.critical(
                self._window,
                "Update failed",
                f"Could not download the update:\n\n{result['err']}",
            )
            return

        # v1.1.1: Replace the post-download Yes/No QMessageBox (which can
        # surface behind a frameless main window and get missed) with an
        # always-on-top countdown banner that auto-fires the installer.
        # The user gets a visible 5-second window to click Cancel.
        self._countdown = InstallCountdown(
            info,
            staged_zip=result["path"],
            parent=self._window,
        )
        self._countdown.show()


# ─────────────────────────────────────────────────────────────────────────────
# Post-download countdown banner (replaces the missable QMessageBox)
# ─────────────────────────────────────────────────────────────────────────────

class InstallCountdown(QWidget):
    """
    Always-on-top non-modal banner shown after the zip downloads.

    Counts down from 5; on zero it calls launch_updater() and quits the
    app. The user can click Cancel to abort, or Install Now to fire
    immediately. Unlike QMessageBox.question() this can't get stuck
    behind the frameless main window — it has WindowStaysOnTopHint and
    its own top-level frame.
    """

    COUNTDOWN_SECONDS = 5

    def __init__(
        self,
        info: UpdateInfo,
        staged_zip: Path,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            None,  # top-level, not parented — so it can't hide behind anything
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._info = info
        self._staged_zip = staged_zip
        self._remaining = self.COUNTDOWN_SECONDS
        self._fired = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            """
            QWidget#card {
                background: #1A1A1F;
                border: 1px solid #FFB347;
                border-radius: 12px;
            }
            QLabel#title { color: #FFB347; font-weight: 700; font-size: 14px; }
            QLabel#body  { color: #E8E8EA; font-size: 12px; }
            QPushButton#primary {
                background: #FFB347; color: #1A1A1F; border: none;
                padding: 8px 16px; border-radius: 6px; font-weight: 700;
            }
            QPushButton#primary:hover { background: #FFC56B; }
            QPushButton#secondary {
                background: transparent; color: #BBB; border: 1px solid #555;
                padding: 8px 14px; border-radius: 6px;
            }
            QPushButton#secondary:hover { color: #FFF; border-color: #888; }
            """
        )

        card = QWidget(self)
        card.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)

        title = QLabel(f"HicoForge v{info.version} ready to install")
        title.setObjectName("title")
        self._body_lbl = QLabel(self._body_text())
        self._body_lbl.setObjectName("body")
        self._body_lbl.setWordWrap(True)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        install_btn = QPushButton("Install Now")
        install_btn.setObjectName("primary")
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(install_btn)

        v.addWidget(title)
        v.addWidget(self._body_lbl)
        v.addLayout(btn_row)

        cancel_btn.clicked.connect(self._on_cancel)
        install_btn.clicked.connect(self._fire)

        # Position center-top of the parent window (or screen)
        self.resize(420, 130)
        self._position(parent)

        # Tick every second
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _body_text(self) -> str:
        return (
            f"Installing in {self._remaining}s. HicoForge will close, "
            "swap in the new version, and reopen. Click Cancel to abort."
        )

    def _position(self, parent: Optional[QWidget]) -> None:
        if parent is not None and parent.isVisible():
            geo = parent.geometry()
            x = geo.center().x() - self.width() // 2
            y = geo.top() + 80
        else:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            x = screen.center().x() - self.width() // 2
            y = screen.top() + 120
        self.move(x, y)

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._fire()
            return
        self._body_lbl.setText(self._body_text())

    def _on_cancel(self) -> None:
        try:
            self._timer.stop()
        finally:
            self.close()

    def _fire(self) -> None:
        if self._fired:
            return
        self._fired = True
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            launch_updater(self._staged_zip, current_version())
        except Exception as exc:
            self.close()
            QMessageBox.critical(
                None,
                "Update failed",
                f"Could not start the updater:\n\n{exc}",
            )
            return
        # Close the app so the .bat can take over
        QApplication.instance().quit()
