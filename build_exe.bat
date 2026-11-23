@echo off
setlocal
cd /d "%~dp0"

if exist "logs" goto skip_mkdir
mkdir "logs" 2>nul
:skip_mkdir

echo [1/4] Preparing Python environment...
python tools\bootstrap.py --setup-only
if errorlevel 1 goto failed

echo [2/4] Installing PyInstaller...
.venv\Scripts\python.exe -m pip install --upgrade pyinstaller
if errorlevel 1 goto failed

echo [3/4] Building MapOverlayRedux.exe (словарь лемм включается через .spec)...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MapOverlayRedux.spec
if errorlevel 1 goto failed

echo [4/4] Checking the lemma dictionary inside the build...
if exist "dist\MapOverlayRedux\_internal\map_overlay\data\lemmas.json" goto built
if exist "dist\MapOverlayRedux\map_overlay\data\lemmas.json" goto built
echo Build failed: словарь лемм не попал в dist\MapOverlayRedux. Поиск работал бы без лемм.
goto failed

:built
echo.
echo Done: dist\MapOverlayRedux\MapOverlayRedux.exe
echo Copy the whole dist\MapOverlayRedux folder next to config\ and logs\.
pause
exit /b 0

:failed
echo Build failed. See logs\setup.log for details.
pause
exit /b 1
