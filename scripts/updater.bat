@echo off
REM ============================================================================
REM HicoForge updater — external folder-swap + restart script.
REM
REM Args:
REM   %1 = full path to the staged zip file (HicoForge-X.Y.Z.zip)
REM   %2 = full path to the install root  (e.g. D:\HicoForge)
REM   %3 = current version string         (used to name the backup folder)
REM
REM Flow:
REM   1. Wait for HicoForge to exit.
REM   2. Move current install to D:\HicoForge_backup_<oldver>\
REM   3. Extract staged zip to a fresh D:\HicoForge\
REM   4. Restore user data (config.json, flows.json, etc.) from the backup.
REM   5. Restart HicoForge.
REM
REM This script is intentionally chatty — it runs in a visible console so
REM the user sees what's happening. Any failure leaves the backup in place,
REM and the user can simply rename it back if they want to roll back.
REM ============================================================================

setlocal EnableDelayedExpansion

set "STAGED_ZIP=%~1"
set "INSTALL_ROOT=%~2"
set "OLD_VERSION=%~3"

if "%STAGED_ZIP%"=="" goto :usage
if "%INSTALL_ROOT%"=="" goto :usage
if "%OLD_VERSION%"=="" set "OLD_VERSION=unknown"

title HicoForge Updater
echo  ================================================================
echo   HicoForge Updater
echo  ================================================================
echo.
echo   Staged zip   : %STAGED_ZIP%
echo   Install root : %INSTALL_ROOT%
echo   Old version  : %OLD_VERSION%
echo.

REM -- Compute backup path next to the install root --------------------------
for %%P in ("%INSTALL_ROOT%") do (
    set "PARENT_DIR=%%~dpP"
    set "INSTALL_NAME=%%~nxP"
)
set "BACKUP_DIR=%PARENT_DIR%%INSTALL_NAME%_backup_%OLD_VERSION%"

REM -- Step 1: wait for HicoForge to exit ------------------------------------
echo  Waiting for HicoForge to close...
set /a TRIES=0
:waitloop
tasklist /FI "IMAGENAME eq pythonw.exe" 2>NUL | find /I "pythonw.exe" >NUL
if not errorlevel 1 (
    set /a TRIES+=1
    if !TRIES! GEQ 30 (
        echo  Warning: HicoForge appears stuck. Force-closing...
        taskkill /F /IM pythonw.exe >NUL 2>&1
        timeout /t 2 /nobreak >NUL
        goto :proceed
    )
    timeout /t 1 /nobreak >NUL
    goto :waitloop
)
:proceed
timeout /t 1 /nobreak >NUL

REM -- Step 2: back up current install ---------------------------------------
echo.
echo  Backing up current install...
echo    -> %BACKUP_DIR%

if exist "%BACKUP_DIR%" (
    echo  Removing previous backup with same version tag...
    rmdir /S /Q "%BACKUP_DIR%"
)

REM Use ROBOCOPY for the move — it handles long paths and locked-but-released
REM files better than `move`. /MOVE deletes the source after copying.
robocopy "%INSTALL_ROOT%" "%BACKUP_DIR%" /MOVE /E /NFL /NDL /NJH /NJS /NC /NS /NP >NUL
if errorlevel 8 (
    echo  ERROR: Backup failed. Aborting update.
    echo  Your install is intact. You can close this window.
    pause
    exit /b 1
)

REM -- Step 3: extract the staged zip into the install root ------------------
echo.
echo  Extracting new version...
mkdir "%INSTALL_ROOT%" 2>NUL

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Expand-Archive -Path '%STAGED_ZIP%' -DestinationPath '%INSTALL_ROOT%' -Force; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"

if errorlevel 1 (
    echo.
    echo  ERROR: Extraction failed. Rolling back...
    rmdir /S /Q "%INSTALL_ROOT%" 2>NUL
    robocopy "%BACKUP_DIR%" "%INSTALL_ROOT%" /MOVE /E /NFL /NDL /NJH /NJS /NC /NS /NP >NUL
    echo  Rolled back to old version.
    pause
    exit /b 1
)

REM If the zip contains a top-level "HicoForge" folder, flatten it.
if exist "%INSTALL_ROOT%\HicoForge\main.py" (
    echo  Flattening nested HicoForge\ folder...
    robocopy "%INSTALL_ROOT%\HicoForge" "%INSTALL_ROOT%" /E /MOVE /NFL /NDL /NJH /NJS /NC /NS /NP >NUL
    rmdir /S /Q "%INSTALL_ROOT%\HicoForge" 2>NUL
)

REM -- Step 4: restore user data from backup ---------------------------------
echo.
echo  Restoring user settings...

REM .venv — copy back (saves the user from re-installing dependencies)
if exist "%BACKUP_DIR%\.venv" (
    echo    -> .venv
    robocopy "%BACKUP_DIR%\.venv" "%INSTALL_ROOT%\.venv" /E /NFL /NDL /NJH /NJS /NC /NS /NP >NUL
)

REM Per-file user data
for %%F in (config.json flows.json) do (
    if exist "%BACKUP_DIR%\%%F" (
        echo    -> %%F
        copy /Y "%BACKUP_DIR%\%%F" "%INSTALL_ROOT%\%%F" >NUL
    )
)

REM -- Step 5: launch the new version ----------------------------------------
echo.
echo  Update complete. Restarting HicoForge...
timeout /t 1 /nobreak >NUL

if exist "%INSTALL_ROOT%\HicoForge.vbs" (
    start "" wscript.exe "%INSTALL_ROOT%\HicoForge.vbs"
) else if exist "%INSTALL_ROOT%\HicoForge.bat" (
    start "" "%INSTALL_ROOT%\HicoForge.bat"
) else (
    echo  Warning: no launcher found in %INSTALL_ROOT%.
    pause
)

REM -- Cleanup staged zip ----------------------------------------------------
if exist "%STAGED_ZIP%" del /Q "%STAGED_ZIP%"

REM Optionally clean staging folder if empty
for %%D in ("%STAGED_ZIP%") do (
    set "STAGING_DIR=%%~dpD"
)
rmdir "%STAGING_DIR%" 2>NUL

REM Auto-close after a short pause so the user can see it succeeded
echo.
echo  Done. This window will close in 3 seconds.
timeout /t 3 /nobreak >NUL
exit /b 0

:usage
echo Usage: updater.bat ^<staged_zip^> ^<install_root^> ^<old_version^>
exit /b 2
