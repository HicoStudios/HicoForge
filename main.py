"""
HicoForge — entry point.

Launches the animated splash. When it finishes, the main window appears.

Run with:
    python main.py

Dependencies:
    pip install PySide6
"""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from app import theme
from app.main_window import MainWindow
from splash import SplashWindow


def _set_windows_app_id():
    """On Windows, set an AppUserModelID so the taskbar groups under HicoForge
    (otherwise it shows as 'python.exe')."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Hico.HicoForge.1"
        )
    except Exception:
        pass


def main():
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("HicoForge")
    app.setOrganizationName("Hico")
    app.setStyleSheet(theme.APP_QSS)

    # Window/taskbar icon (Alt+Tab + taskbar will pick this up; the Start Menu
    # and Desktop shortcuts also point at the same .ico file).
    icon_path = Path(__file__).parent / "assets" / "HicoForge.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Hi-DPI niceties
    try:
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass

    # The main window is created up front but kept hidden until splash finishes,
    # so the very first paint of the main window happens behind the splash.
    main_window = MainWindow()

    def on_splash_done():
        main_window.show()
        main_window.raise_()
        main_window.activateWindow()

    splash = SplashWindow(on_finished=on_splash_done)
    splash.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
