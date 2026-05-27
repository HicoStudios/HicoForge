"""
HicoForge - Surgical patch for app/main_window.py

Adds:
  1. UpdateManager import
  2. Title bar update button (circular arrow, between settings and minimize)
  3. Silent update check at end of __init__
  4. _open_update_check() method

Safe to re-run: skips if already patched.
Auto-backs-up to app/main_window.py.bak before any change.
Auto-restores backup if the result doesn't compile.

Usage:
    D:\\HicoForge\\.venv\\Scripts\\python.exe patch_main_window.py
"""

import ast
import shutil
import sys
from pathlib import Path

TARGET = Path(r"D:\HicoForge\app\main_window.py")


def fail(msg):
    print(f"  [FAIL] {msg}")
    sys.exit(1)


def ok(msg):
    print(f"  [OK]   {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def main():
    print()
    print("HicoForge MainWindow updater patch")
    print("===================================")

    if not TARGET.exists():
        fail(f"{TARGET} not found")

    content = TARGET.read_text(encoding="utf-8")

    if "from app.update_dialog import UpdateManager" in content:
        warn("Already patched - nothing to do")
        return

    # ---------- Backup ----------
    backup = TARGET.with_suffix(TARGET.suffix + ".bak")
    i = 1
    while backup.exists():
        backup = TARGET.with_suffix(TARGET.suffix + f".bak{i}")
        i += 1
    shutil.copy2(TARGET, backup)
    ok(f"Backup -> {backup}")

    # ---------- Patch 1: import ----------
    anchor = "from app.toast import ToastManager"
    if anchor not in content:
        fail(f"Import anchor missing: {anchor}")
    content = content.replace(
        anchor,
        anchor + "\nfrom app.update_dialog import UpdateManager",
        1,
    )
    ok("Added UpdateManager import")

    # ---------- Patch 2: title bar button ----------
    # Insert update button BEFORE the minimize button line.
    # Anchor: "        min_btn = QPushButton("
    title_anchor = "        min_btn = QPushButton("
    if title_anchor not in content:
        fail("Title bar minimize anchor missing")

    update_btn_block = (
        '        update_btn = QPushButton("\u21BB")\n'
        '        update_btn.setObjectName("WinBtn")\n'
        '        update_btn.setCursor(Qt.PointingHandCursor)\n'
        '        update_btn.setToolTip("Check for updates")\n'
        '        update_btn.clicked.connect(self._open_update_check)\n'
        '        h.addWidget(update_btn)\n'
        '\n'
        + title_anchor
    )
    content = content.replace(title_anchor, update_btn_block, 1)
    ok("Added update button to title bar")

    # ---------- Patch 3: end of __init__ ----------
    init_anchor = "        QTimer.singleShot(600, self._restore_pending_queue)"
    if init_anchor not in content:
        fail("End-of-__init__ anchor missing")

    init_tail = (
        init_anchor + "\n"
        "\n"
        "        # --- Auto-updater ---\n"
        "        try:\n"
        "            self.update_manager = UpdateManager(self)\n"
        "            QTimer.singleShot(3000, self.update_manager.check_silently)\n"
        "        except Exception as _upd_err:\n"
        '            print(f"[updater] init failed: {_upd_err}")\n'
    )
    content = content.replace(init_anchor, init_tail, 1)
    ok("Added UpdateManager init at end of __init__")

    # ---------- Patch 4: _open_update_check method ----------
    method_anchor = "    # ---- Title bar ----\n    def _build_title_bar(self):"
    if method_anchor not in content:
        fail("Title bar method anchor missing")

    method_block = (
        "    # ---- Updater ----\n"
        "    def _open_update_check(self):\n"
        '        """Title bar update button - force a manual check."""\n'
        "        try:\n"
        "            self.update_manager.check_manually()\n"
        "        except Exception as _e:\n"
        '            print(f"[updater] manual check failed: {_e}")\n'
        "\n"
        + method_anchor
    )
    content = content.replace(method_anchor, method_block, 1)
    ok("Added _open_update_check method")

    # ---------- Syntax check before writing ----------
    try:
        ast.parse(content)
    except SyntaxError as e:
        fail(f"Patched content has syntax error: {e}")

    # ---------- Write ----------
    TARGET.write_text(content, encoding="utf-8")
    ok("Wrote patched main_window.py")

    # ---------- Final verify with py_compile ----------
    import py_compile
    try:
        py_compile.compile(str(TARGET), doraise=True)
        ok("Compiles cleanly")
    except py_compile.PyCompileError as e:
        warn(f"Compile failed: {e}")
        warn("Restoring backup...")
        shutil.copy2(backup, TARGET)
        fail("Restored. Send the error above to Computer.")

    print()
    print("===================================")
    print("  Patch complete!")
    print("===================================")
    print()
    print("Test it:")
    print("  1. Launch:  D:\\HicoForge\\HicoForge.vbs")
    print("  2. Look for a refresh-arrow button in the title bar")
    print("     (between settings gear and minimize dash)")
    print("  3. Click it - should say 'You're up to date (1.0.0)'")
    print()
    print(f"To undo:  Copy-Item {backup} {TARGET} -Force")
    print()


if __name__ == "__main__":
    main()
