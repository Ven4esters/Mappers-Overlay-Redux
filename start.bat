@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title Screensaver into Discord

echo ================================================
echo   Screensaver into Discord - %cd%
echo ================================================
echo.

REM --- 1. Найти Python (3.12 предпочтительнее) / Find Python (3.12 preferred) ---
set "PYTHON="
py -3.12 --version >nul 2>nul
if %errorlevel%==0 set "PYTHON=py -3.12"
if not defined PYTHON (
    python --version >nul 2>nul
    if %errorlevel%==0 set "PYTHON=python"
)
if not defined PYTHON (
    python3 --version >nul 2>nul
    if %errorlevel%==0 set "PYTHON=python3"
)
if not defined PYTHON (
    echo [ОШИБКА / ERROR] Python не найден. Установите Python 3.12 с python.org
    echo                   и отметьте «Add python.exe to PATH» при установке.
    echo [ERROR] Python was not found. Install Python 3.12 from python.org
    echo         and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('%PYTHON% --version 2^>^&1') do echo Python: %%v

REM --- 2. Создать виртуальное окружение при первом запуске / Create venv on first run ---
if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение .venv ... / Creating .venv ...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo [ОШИБКА / ERROR] Не удалось создать .venv. Проверьте установку Python.
        pause
        exit /b 1
    )
)
set "VENV_PY=.venv\Scripts\python.exe"

REM --- 3. Установить зависимости (тихо, идемпотентно) / Install deps (quiet, idempotent) ---
echo Проверяю зависимости ... / Checking dependencies ...
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo [ОШИБКА / ERROR] Не удалось установить зависимости.
    echo Проверьте интернет и повторите запуск. Детали выше.
    pause
    exit /b 1
)

REM --- 4. Запустить приложение / Launch the app ---
echo Запускаю ... / Starting ...
echo.
"%VENV_PY%" main.py
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ОШИБКА / ERROR] Приложение завершилось с кодом %APP_EXIT%.
    echo Если это первая установка — попробуйте удалить папку .venv и запустить снова.
    echo If this is a fresh install - try deleting the .venv folder and run again.
    pause
)
exit /b %APP_EXIT%
