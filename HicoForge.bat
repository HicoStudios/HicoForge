@echo off
REM HicoForge.bat — debug launcher (keeps a console window for stdout/stderr).
REM For the silent launch used by Desktop/Start Menu shortcuts, see HicoForge.vbs.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo HicoForge: virtual environment missing. Run setup.bat first.
    pause
    exit /b 1
)

"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\main.py" %*
endlocal
