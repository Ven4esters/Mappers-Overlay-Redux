@echo off
setlocal
cd /d "%~dp0"

rem Installs Python environment for LSP Mapper Overlay (venv + PySide6).
rem ASCII only: Windows console uses cp866. Logic lives in tools\bootstrap.py

echo === LSP Mapper Overlay: environment setup ===
echo.

if exist ".venv\Scripts\python.exe" goto have_venv

where py >nul 2>nul
if errorlevel 1 goto try_python
py -3.12 "tools\bootstrap.py" --install-only %*
goto finish

:try_python
python "tools\bootstrap.py" --install-only %*
goto finish

:have_venv
".venv\Scripts\python.exe" "tools\bootstrap.py" --install-only %*

:finish
if errorlevel 1 goto failed
echo.
echo Environment is ready. Start the overlay with run_mapper.bat
pause
exit /b 0

:failed
echo.
echo Environment setup failed. See logs\setup.log for details.
pause
exit /b 1
