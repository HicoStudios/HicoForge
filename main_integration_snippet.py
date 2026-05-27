"""
HicoForge main.py integration snippet for the auto-updater.

Merge these pieces into your existing D:\\HicoForge\\main.py.
Do NOT replace your main.py — just add the marked sections.
"""

# ============================================================================
# SECTION 1: Imports — add near the top of main.py with your other imports
# ============================================================================
from version import __version__
from app.update_dialog import UpdateManager
from PySide6.QtGui import QAction
from PySide6.QtCore import QTimer


# ============================================================================
# SECTION 2: At the END of MainWindow.__init__ (after self.show() / setup)
#
# UpdateManager pulls the current version from version.py and the repo
# from core/updater.py constants automatically — just pass the window.
# ============================================================================

# Inside MainWindow.__init__(self):
#     ... your existing init code ...
#
#     # --- Auto-updater ---
#     self.update_manager = UpdateManager(self)
#     # Silent check 3 seconds after launch (lets UI settle first)
#     QTimer.singleShot(3000, self.update_manager.check_silently)


# ============================================================================
# SECTION 3: Help menu — add "Check for Updates..." and "About"
#
# Find your menu bar setup (look for self.menuBar() or addMenu).
# ============================================================================

# In your menu setup code:
#
#     help_menu = self.menuBar().addMenu("&Help")
#
#     check_updates_action = QAction("Check for &Updates...", self)
#     check_updates_action.triggered.connect(self.update_manager.check_manually)
#     help_menu.addAction(check_updates_action)
#
#     help_menu.addSeparator()
#
#     about_action = QAction("&About HicoForge", self)
#     about_action.triggered.connect(self._show_about)
#     help_menu.addAction(about_action)


# ============================================================================
# SECTION 4: About dialog method — add as a method on MainWindow
# ============================================================================

def _show_about(self):
    """Show the About dialog with version info."""
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.about(
        self,
        "About HicoForge",
        f"<h3>HicoForge</h3>"
        f"<p>Version {__version__}</p>"
        f"<p>Part of the Hico family of apps.</p>"
        f"<p><a href='https://github.com/HicoStudios/HicoForge'>"
        f"github.com/HicoStudios/HicoForge</a></p>"
    )


# ============================================================================
# SECTION 5: Window title — show version (optional but nice)
# ============================================================================

# self.setWindowTitle(f"HicoForge {__version__}")
