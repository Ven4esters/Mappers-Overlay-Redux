@echo off
setlocal
cd /d "%~dp0"

if exist "logs" goto skip_mkdir
mkdir "logs" 2>nul
:skip_mkdir

where py >nul 2>&1
if errorlevel 1 goto use_python
py -3.12 -c "import sys" >nul 2>&1
if errorlevel 1 goto use_python
py -3.12 tools\bootstrap.py %*
if errorlevel 1 goto failed
goto done

:use_python
where python >nul 2>&1
if errorlevel 1 goto no_python
python tools\bootstrap.py %*
if errorlevel 1 goto failed
goto done

:no_python
echo Python not found. Install Python 3.12 from python.org and enable "Add python.exe to PATH".
echo See logs\setup.log for details.
pause
exit /b 1

:failed
echo Startup failed. See logs\setup.log for details.
pause
exit /b 1

:done
endlocal
exit /b 0
