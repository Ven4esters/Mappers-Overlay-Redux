@echo off
rem ============================================================================
rem  LSP Mapper Assist - launcher
rem  1) создаёт виртуальное окружение .venv (если его нет или оно битое)
rem  2) доустанавливает / обновляет зависимости из requirements.txt
rem  3) запускает приложение
rem  Все действия пишутся в logs\setup.log, ошибки приложения - в logs\mapper_assist.log
rem
rem  Ключи запуска:
rem    run_mapper.bat              - обычный запуск (без консоли)
rem    run_mapper.bat --debug      - запуск с консолью и подробным логом
rem    run_mapper.bat --reinstall  - принудительно переустановить зависимости
rem    run_mapper.bat --repair-venv- удалить .venv и создать окружение заново
rem ============================================================================

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title LSP Mapper Assist
pushd "%~dp0"

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "LOGDIR=%ROOT%logs"
set "SETUP_LOG=%LOGDIR%\setup.log"
set "APP_LOG=%LOGDIR%\mapper_assist.log"
set "READY_MARKER=%LOGDIR%\session_ready.txt"
set "STAMP=%VENV%\.deps-stamp"
set "REQ_FILE=%ROOT%requirements.txt"
set "DEBUG=0"
set "FORCE=0"
set "REPAIR=0"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--debug" set "DEBUG=1"
if /i "%~1"=="--reinstall" set "FORCE=1"
if /i "%~1"=="--repair-venv" ( set "REPAIR=1" & set "FORCE=1" )
shift
goto parse_args
:args_done

if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1

rem Ротация журнала установки, чтобы он не рос бесконечно
if exist "%SETUP_LOG%" for %%A in ("%SETUP_LOG%") do if %%~zA GTR 1048576 move /y "%SETUP_LOG%" "%SETUP_LOG%.1" >nul 2>&1

call :log "=============================================================="
call :log " LSP Mapper Assist: подготовка окружения"
call :log " Дата: %DATE% %TIME% | Каталог: %ROOT%"
call :log "=============================================================="

if not exist "%ROOT%main.py" (
    call :fail "Не найден main.py рядом с run_mapper.bat. Распакуйте архив полностью."
    pause
    exit /b 1
)

if not exist "%REQ_FILE%" (
    call :fail "Не найден файл requirements.txt рядом с run_mapper.bat."
    call :tail_log
    pause
    exit /b 1
)

rem ---------------------------------------------------------------- 1. Python
call :log "[1/5] Поиск установленного Python..."
set "BASE_PY="
where py >nul 2>&1
if not errorlevel 1 set "BASE_PY=py -3"
if not defined BASE_PY (
    where python >nul 2>&1
    if not errorlevel 1 set "BASE_PY=python"
)
if not defined BASE_PY (
    call :fail "Python не найден в PATH. Установите Python 3.10+ с python.org (галочка 'Add python.exe to PATH')."
    call :tail_log
    pause
    exit /b 1
)
for /f "tokens=2" %%V in ('%BASE_PY% --version 2^>^&1') do set "PY_VER=%%V"
call :log "      Найден Python %PY_VER% (%BASE_PY%)"

rem ---------------------------------------------------------------- 2. venv
if "%REPAIR%"=="1" (
    if exist "%VENV%" (
        call :log "[2/5] --repair-venv: удаляю существующее окружение .venv ..."
        rmdir /s /q "%VENV%" >>"%SETUP_LOG%" 2>&1
    )
)

if not exist "%PY%" (
    call :log "[2/5] Создаю виртуальное окружение .venv (первый запуск, ~10 сек)..."
    %BASE_PY% -m venv "%VENV%" >>"%SETUP_LOG%" 2>&1
    if errorlevel 1 goto venv_failed
    call :log "      Готово: %VENV%"
) else (
    call :log "[2/5] Виртуальное окружение найдено, проверяю целостность..."
)

"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    call :log "      Окружение повреждено - пересоздаю."
    rmdir /s /q "%VENV%" >>"%SETUP_LOG%" 2>&1
    %BASE_PY% -m venv "%VENV%" >>"%SETUP_LOG%" 2>&1
    if errorlevel 1 goto venv_failed
)

rem ---------------------------------------------------------------- 3. зависимости
call :log "[3/5] Проверка зависимостей (PySide6, pyperclip)..."
set "REQ_HASH=unknown"
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%REQ_FILE%" MD5 2^>nul') do (
    if "!REQ_HASH!"=="unknown" set "REQ_HASH=%%H"
)
set "OLD_HASH="
if exist "%STAMP%" for /f "usebackq delims=" %%H in ("%STAMP%") do set "OLD_HASH=%%H"

set "NEED_INSTALL=0"
if "%FORCE%"=="1" set "NEED_INSTALL=1"
if /i not "%REQ_HASH%"=="%OLD_HASH%" set "NEED_INSTALL=1"
"%PY%" -c "import PySide6, pyperclip" >nul 2>&1
if errorlevel 1 set "NEED_INSTALL=1"

if "%NEED_INSTALL%"=="0" (
    call :log "      Все зависимости уже установлены - скачивание не требуется."
) else (
    call :log "[4/5] Установка зависимостей (нужен интернет, может занять 1-3 минуты)..."
    "%PY%" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel >>"%SETUP_LOG%" 2>&1
    "%PY%" -m pip install --disable-pip-version-check --upgrade -r "%REQ_FILE%" >>"%SETUP_LOG%" 2>&1
    if errorlevel 1 (
        call :fail "Не удалось установить зависимости."
        call :log "      Последние строки logs\setup.log:"
        call :tail_log
        call :log "      Что можно попробовать:"
        call :log "        1) проверить интернет / VPN / прокси;"
        call :log "        2) запустить: run_mapper.bat --repair-venv"
        pause
        exit /b 1
    )
    "%PY%" -c "import PySide6, pyperclip" >nul 2>&1
    if errorlevel 1 (
        call :fail "Зависимости установились, но не импортируются."
        call :tail_log
        pause
        exit /b 1
    )
    >"%STAMP%" echo %REQ_HASH%
    call :log "      Зависимости установлены и проверены."
)

rem ---------------------------------------------------------------- 4. запуск
if exist "%READY_MARKER%" del /q "%READY_MARKER%" >nul 2>&1

if "%DEBUG%"=="1" (
    call :log "[5/5] Запуск в режиме отладки (консоль остаётся открытой)..."
    "%PY%" "%ROOT%main.py" --debug
    set "APP_EXIT=!errorlevel!"
    call :log "Приложение завершилось с кодом !APP_EXIT!."
    if not "!APP_EXIT!"=="0" call :tail_log
    popd
    endlocal & exit /b !APP_EXIT!
)

call :log "[5/5] Запуск приложения..."
start "" "%PYW%" "%ROOT%main.py"

set /a WAIT_TICKS=0
:wait_ready
if exist "%READY_MARKER%" goto app_started
set /a WAIT_TICKS+=1
if %WAIT_TICKS% GEQ 12 goto app_not_started
ping -n 2 127.0.0.1 >nul
goto wait_ready

:app_started
call :log "Окно приложения открыто. Для выхода используйте кнопку закрытия в оверлее."
call :log "Логи: %APP_LOG%"
popd
endlocal & exit /b 0

:app_not_started
call :fail "Приложение не сообщило об успешном старте за 12 секунд."
call :log "      Последние строки logs\mapper_assist.log:"
call :tail_app_log
pause
popd
endlocal & exit /b 1

:venv_failed
call :fail "Не удалось создать виртуальное окружение .venv."
call :tail_log
call :log "      Проверьте, что установлен Python с модулем venv, и есть права на запись в папку проекта."
pause
popd
endlocal & exit /b 1

rem ---------------------------------------------------------------- helpers
:log
echo %~1
>>"%SETUP_LOG%" echo [%DATE% %TIME%] %~1
exit /b 0

:fail
echo.
echo [ОШИБКА] %~1
>>"%SETUP_LOG%" echo [%DATE% %TIME%] [ОШИБКА] %~1
echo.
exit /b 0

:tail_log
if exist "%SETUP_LOG%" powershell -NoProfile -Command "Get-Content -LiteralPath '%SETUP_LOG%' -Tail 25 -Encoding UTF8" 2>nul
exit /b 0

:tail_app_log
if exist "%APP_LOG%" powershell -NoProfile -Command "Get-Content -LiteralPath '%APP_LOG%' -Tail 25 -Encoding UTF8" 2>nul
exit /b 0
