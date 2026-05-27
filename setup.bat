@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ===========================================================
REM HicoForge installer
REM   - Creates a local virtual environment (.venv)
REM   - Installs requirements
REM   - Creates Desktop + Start Menu shortcuts pointing at the
REM     silent launcher, using HicoForge.ico
REM ===========================================================

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

echo.
echo  ====================================================
echo   HicoForge Setup
echo   Install folder: %ROOT%
echo  ====================================================
echo.

REM --- Locate Python ---
set "PYEXE="
for %%P in (py python3 python) do (
    if not defined PYEXE (
        where %%P >nul 2>nul && set "PYEXE=%%P"
    )
)
if not defined PYEXE (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.12 from https://www.python.org/downloads/ and re-run.
    pause
    exit /b 1
)
echo Using Python launcher: %PYEXE%

REM --- Create venv if missing ---
if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    if /I "%PYEXE%"=="py" (
        py -3.12 -m venv "%ROOT%\.venv" 2>nul || py -3 -m venv "%ROOT%\.venv" || (
            echo [ERROR] Failed to create virtual environment.
            pause & exit /b 1
        )
    ) else (
        %PYEXE% -m venv "%ROOT%\.venv" || (
            echo [ERROR] Failed to create virtual environment.
            pause & exit /b 1
        )
    )
) else (
    echo Reusing existing virtual environment at .venv
)

set "VPY=%ROOT%\.venv\Scripts\python.exe"

REM --- Upgrade pip + install requirements ---
echo.
echo Installing dependencies (this may take a few minutes)...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r "%ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Dependency install failed.
    pause
    exit /b 1
)

REM --- Optional: rembg for background removal tile ---
echo.
choice /M "Install optional Background Removal (rembg + onnxruntime-gpu, ~400 MB)"
if not errorlevel 2 (
    echo Installing rembg ...
    "%VPY%" -m pip install rembg onnxruntime-gpu
)

REM --- Build the shortcuts via PowerShell ---
echo.
echo Creating Desktop and Start Menu shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\install_shortcuts.ps1" -InstallRoot "%ROOT%"
if errorlevel 1 (
    echo [WARN] Shortcut creation failed. You can still launch with HicoForge.bat.
)

echo.
echo  ====================================================
echo   Done. Look for the HicoForge icon on your Desktop
echo   and in your Start Menu.
echo  ====================================================
echo.
pause
endlocal
