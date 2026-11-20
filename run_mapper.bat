@echo off
rem ===========================================================================
rem  LSP Mapper Assist - launcher (ASCII only, safe with any codepage)
rem  All real work (venv, pip, launch, diagnostics) is done by tools\bootstrap.py
rem  so this file cannot break on encoding or cmd parsing.
rem
rem  Args:
rem    run_mapper.bat                normal launch (no console window left behind)
rem    run_mapper.bat --debug        launch with console and verbose log
rem    run_mapper.bat --reinstall    force reinstall of dependencies
rem    run_mapper.bat --repair-venv  delete .venv and recreate it
rem    run_mapper.bat --check-only   prepare/verify environment, do not launch
rem ===========================================================================

setlocal EnableExtensions
title LSP Mapper Assist
cd /d "%~dp0"

if not exist "logs" mkdir "logs" >nul 2>&1

echo LSP Mapper Assist: preparing environment...
echo (first run can take 1-3 minutes while dependencies are downloaded)
echo.

if not exist "main.py" (
    echo [ERROR] main.py not found next to run_mapper.bat.
    echo Unpack the archive completely and start run_mapper.bat from that folder.
    echo.
    pause
    exit /b 1
)

if not exist "tools\bootstrap.py" (
    echo [ERROR] tools\bootstrap.py not found.
    echo Unpack the archive completely and start run_mapper.bat from that folder.
    echo.
    pause
    exit /b 1
)

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [ERROR] Python 3.10 or newer was not found in PATH.
    echo Install it from https://www.python.org/downloads/
    echo During installation enable "Add python.exe to PATH".
    echo.
    echo Details: logs\setup.log
    pause
    exit /b 1
)

%PY_CMD% "tools\bootstrap.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [ERROR] Startup failed. Exit code: %RC%
    echo See logs\setup.log and logs\mapper_assist.log
    echo.
    pause
    exit /b %RC%
)

exit /b 0
