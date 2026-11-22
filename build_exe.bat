@echo off
setlocal
cd /d "%~dp0"

if exist "logs" goto skip_mkdir
mkdir "logs" 2>nul
:skip_mkdir

echo [1/3] Preparing Python environment...
python tools\bootstrap.py --setup-only
if errorlevel 1 goto failed

echo [2/3] Installing PyInstaller...
.venv\Scripts\python.exe -m pip install --upgrade pyinstaller
if errorlevel 1 goto failed

echo [3/3] Building MapOverlayRedux.exe...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name MapOverlayRedux main.py
if errorlevel 1 goto failed

echo.
echo Done: dist\MapOverlayRedux\MapOverlayRedux.exe
echo Copy the whole dist\MapOverlayRedux folder next to config\ and logs\.
pause
exit /b 0

:failed
echo Build failed. See logs\setup.log for details.
pause
exit /b 1
