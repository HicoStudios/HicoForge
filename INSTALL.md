# HicoForge Auto-Updater — Install Guide

Adds a Check for Updates button + silent auto-check on launch. Updates ship as GitHub Releases.

---

## Step 1 — Drop in the files

From the zip, copy these into your HicoForge install:

```
hicoforge_updater_v1.zip
├── version.py                  →  D:\HicoForge\version.py
├── core\updater.py             →  D:\HicoForge\core\updater.py
├── scripts\updater.bat         →  D:\HicoForge\scripts\updater.bat
└── app\update_dialog.py        →  D:\HicoForge\app\update_dialog.py
```

In PowerShell:

```powershell
cd D:\HicoForge
Expand-Archive -Path "$env:USERPROFILE\Downloads\hicoforge_updater_v1.zip" -DestinationPath . -Force
```

If `core\`, `scripts\`, or `app\` don't exist yet, the extract creates them. Both `core` and `app` need an `__init__.py` (empty file) if they don't have one:

```powershell
ni core\__init__.py -ItemType File -Force | Out-Null
ni app\__init__.py -ItemType File -Force | Out-Null
```

---

## Step 2 — Wire into main.py

Open `D:\HicoForge\main.py` and follow `main_integration_snippet.py` (in the zip). Five small edits:

**1. Imports (top of file):**
```python
from version import __version__
from app.update_dialog import UpdateManager
from PySide6.QtGui import QAction
from PySide6.QtCore import QTimer
```

**2. End of `MainWindow.__init__`:**
```python
self.update_manager = UpdateManager(self)
QTimer.singleShot(3000, self.update_manager.check_silently)
```

(Repo + version are read automatically from `core/updater.py` and `version.py` — no args needed.)

**3. Add a Help menu** (wherever you build the menu bar):
```python
help_menu = self.menuBar().addMenu("&Help")

check_updates_action = QAction("Check for &Updates...", self)
check_updates_action.triggered.connect(self.update_manager.check_manually)
help_menu.addAction(check_updates_action)
```

**4. Window title with version (optional):**
```python
self.setWindowTitle(f"HicoForge {__version__}")
```

**5. Save main.py.**

---

## Step 3 — Test locally (still v1.0.0)

```powershell
cd D:\HicoForge
.\HicoForge.vbs
```

- App should open normally
- Help menu → "Check for Updates..." → should say **"You're up to date (1.0.0)."**
- No toast on launch (because no newer release exists yet)

If anything errors out, check that `core\__init__.py` and `app\__init__.py` exist.

---

## Step 4 — Commit + push the updater

```powershell
cd D:\HicoForge
git add version.py core/updater.py scripts/updater.bat app/update_dialog.py app/__init__.py core/__init__.py main.py
git commit -m "Add auto-updater (v1.0.0 baseline)"
git push
```

---

## Step 5 — Publish the v1.0.0 baseline release

The updater needs a release on GitHub to compare against. Publish v1.0.0 first.

**Build the release zip** (everything except .venv, output, models, configs):

```powershell
cd D:\HicoForge
$exclude = @('.venv','output','models','temp','__pycache__','HicoForge_backup_*','*_update_staging','.git','config.json','flows.json')
$tempDir = "$env:TEMP\HicoForge-1.0.0"
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
robocopy D:\HicoForge $tempDir /E /XD .venv output models temp __pycache__ .git /XF config.json flows.json | Out-Null
Compress-Archive -Path "$tempDir\*" -DestinationPath "$env:USERPROFILE\Downloads\HicoForge-1.0.0.zip" -Force
Write-Host "Built: $env:USERPROFILE\Downloads\HicoForge-1.0.0.zip"
```

**Tag + create the release:**

```powershell
cd D:\HicoForge
git tag v1.0.0
git push origin v1.0.0
```

Then on GitHub:
1. Go to https://github.com/HicoStudios/HicoForge/releases
2. Click **"Draft a new release"**
3. **Tag:** `v1.0.0` (select existing)
4. **Title:** `HicoForge 1.0.0`
5. **Description:**
   ```
   Initial baseline release.

   SHA256: <paste hash here>
   ```
6. **Upload `HicoForge-1.0.0.zip`** as a release asset
7. Click **"Publish release"**

Get the SHA256 with:
```powershell
(Get-FileHash "$env:USERPROFILE\Downloads\HicoForge-1.0.0.zip" -Algorithm SHA256).Hash
```

---

## Step 6 — Test the full update flow (v1.0.1)

Now ship a fake v1.0.1 to verify the updater actually works.

1. Open `D:\HicoForge\version.py`, change to `__version__ = "1.0.1"`
2. Make any tiny visible change (e.g. window title text)
3. Commit + push:
   ```powershell
   git add . ; git commit -m "v1.0.1 test" ; git push
   ```
4. Rebuild the zip (rerun Step 5 build command, change `1.0.0` → `1.0.1`)
5. Tag + push:
   ```powershell
   git tag v1.0.1 ; git push origin v1.0.1
   ```
6. Publish release v1.0.1 on GitHub with the zip + SHA256

**Now revert your local version.py back to 1.0.0**, launch HicoForge, and:
- ~3 seconds after launch a toast should appear: *"HicoForge 1.0.1 is available"*
- Click **Install** → downloads, verifies, closes the app, updater.bat runs, app restarts on 1.0.1
- Your `config.json`, `flows.json`, and `.venv` should all survive
- A `HicoForge_backup_1.0.0\` folder will be next to your install in case anything broke

---

## How releases work going forward

Every time you ship an update:

1. Bump `version.py` (e.g. 1.0.1 → 1.1.0)
2. Commit + push
3. Build the zip (Step 5 build command, swap version number)
4. `git tag v1.1.0 && git push origin v1.1.0`
5. On GitHub: Draft release → tag v1.1.0 → upload zip → paste SHA256 in body → publish

All existing users get the toast on next launch.

---

## Versioning convention

- `v1.0.0` → `v1.0.1` = bugfix
- `v1.0.0` → `v1.1.0` = new feature (Flow Tiles ships as v1.1.0)
- `v1.0.0` → `v2.0.0` = breaking change

The updater tag format is `vMAJOR.MINOR.PATCH` — the leading `v` is stripped during comparison.

---

## Troubleshooting

**"You're up to date" but I just published 1.0.1:**
GitHub API can take ~30 seconds to expose new releases. Wait a minute and try again.

**Update downloaded but app didn't restart:**
Check that `D:\HicoForge\HicoForge.vbs` exists. The updater.bat looks for it to silently restart. If you renamed it, edit `scripts\updater.bat` line that says `start "" "%INSTALL_DIR%\HicoForge.vbs"`.

**SHA256 mismatch error:**
Either you uploaded a different zip than you hashed, or you typed the hash wrong in the release body. Re-hash the uploaded zip and edit the release.

**Want to skip verification temporarily:**
Just don't put a `SHA256:` line in the release body. The updater will skip the check.
