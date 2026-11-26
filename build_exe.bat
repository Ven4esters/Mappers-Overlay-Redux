@echo off
rem Кириллица в консоли: файл в UTF-8, без chcp сообщения выглядят мусором.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist "logs" goto skip_mkdir
mkdir "logs" 2>nul
:skip_mkdir

echo [1/6] Preparing Python environment...
python tools\bootstrap.py --setup-only
if errorlevel 1 goto failed

echo [2/6] Installing PyInstaller...
.venv\Scripts\python.exe -m pip install --upgrade pyinstaller
if errorlevel 1 goto failed

echo [3/6] Checking icon and lemma dictionary...
if not exist "map_overlay\data\lemmas.json" goto no_lemmas
if not exist "map_overlay\data\app.ico" goto no_icon

echo [4/6] Building MappersOverlayRedux.exe (словарь лемм и иконка включаются через .spec)...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean MappersOverlayRedux.spec
if errorlevel 1 goto failed

echo [5/6] Checking the build and packing it into a zip...
if exist "dist\MappersOverlayRedux\_internal\map_overlay\data\lemmas.json" goto packed
if exist "dist\MappersOverlayRedux\map_overlay\data\lemmas.json" goto packed
echo Build failed: словарь лемм не попал в dist\MappersOverlayRedux. Поиск работал бы без лемм.
goto failed

:packed
.venv\Scripts\python.exe -m tools.make_exe_report --exe "dist\MappersOverlayRedux\MappersOverlayRedux.exe" --pack "dist\MappersOverlayRedux" --out "dist\release" > "logs\release-report.txt"
if errorlevel 1 goto failed

echo [6/6] Checking the release files...
for /f "delims=" %%v in ('.venv\Scripts\python.exe -c "import map_overlay;print(map_overlay.__version__)"') do set VERSION=%%v
if not exist "dist\release\MappersOverlayRedux.exe.md5" goto no_report
if not exist "dist\release\MappersOverlayRedux.exe.sha256" goto no_report
if not exist "dist\release\MD5SUMS.txt" goto no_report
if not exist "dist\release\SHA256SUMS.txt" goto no_report
if not exist "dist\release\README-exe.md" goto no_report

echo.
echo Done: dist\MappersOverlayRedux\MappersOverlayRedux.exe
echo Release files: dist\release
echo   MappersOverlayRedux.exe.md5      - MD5 скомпилированного exe
echo   MappersOverlayRedux.exe.sha256   - SHA256 скомпилированного exe
echo   MD5SUMS.txt / SHA256SUMS.txt     - суммы всех файлов релиза
echo   MappersOverlayRedux_*_win64.zip  - архив папки сборки (детерминированный)
echo   build-info.json                  - те же данные машинно-читаемо
echo   README-exe.md                    - готовый блок для раздела «Скачать готовую сборку»
echo.
echo Next:
echo   1. Open dist\release\README-exe.md, загрузите exe на virustotal.com и впишите ссылку
echo      в строку VirusTotal этого файла (сейчас там TODO).
echo   2. Вставьте содержимое README-exe.md в README.md вместо таблицы в разделе
echo      «Скачать готовую сборку».
echo   3. Приложите файлы к релизу тега:
echo        gh release upload v%VERSION% "dist\release\MappersOverlayRedux.exe"
echo        gh release upload v%VERSION% "dist\release\MappersOverlayRedux_%VERSION%_win64.zip"
echo        gh release upload v%VERSION% "dist\release\MD5SUMS.txt" "dist\release\SHA256SUMS.txt"
echo.
echo Copy the whole dist\MappersOverlayRedux folder next to config\ and logs\ if you run it locally.
pause
exit /b 0

:no_lemmas
echo Build stopped: нет map_overlay\data\lemmas.json — поиск по библиотеке работал бы без лемм.
goto failed

:no_icon
echo Build stopped: нет map_overlay\data\app.ico — соберите иконку: python -m tools.make_icons
goto failed

:no_report
echo Build failed: отчёт dist\release собран не полностью. Смотрите logs\release-report.txt.
goto failed

:failed
echo Build failed. See logs\setup.log and logs\release-report.txt for details.
pause
exit /b 1
