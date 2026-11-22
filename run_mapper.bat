@echo off
setlocal
cd /d "%~dp0"

rem Launcher for LSP Mapper Overlay. ASCII only: Windows console uses cp866.
rem All logic lives in tools\bootstrap.py so errors are logged and explained.

if exist ".venv\Scripts\python.exe" goto have_venv

where py >nul 2>nul
if errorlevel 1 goto try_python
py -3.12 "tools\bootstrap.py" %*
if errorlevel 1 goto failed
goto done

:try_python
python "tools\bootstrap.py" %*
if errorlevel 1 goto failed
goto done

:have_venv
".venv\Scripts\python.exe" "tools\bootstrap.py" %*
if errorlevel 1 goto failed
goto done

:failed
echo.
echo Something went wrong. See logs\setup.log for details.
pause
exit /b 1

:done
endlocal
