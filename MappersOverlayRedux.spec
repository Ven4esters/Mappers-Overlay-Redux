# -*- mode: python ; coding: utf-8 -*-
"""Сборка MappersOverlayRedux.exe (PyInstaller).

Кроме кода в exe обязан попасть словарь лемм `map_overlay/data/lemmas.json`:
без него поиск по библиотеке размеров работает только по окончаниям слов.
Поэтому сборка идёт по этому файлу (`build_exe.bat`), а не по `main.py` напрямую.
"""

from pathlib import Path

LEMMAS = Path("map_overlay") / "data" / "lemmas.json"
if not LEMMAS.is_file():
    raise SystemExit(f"Нет файла словаря лемм: {LEMMAS} — сборка остановлена.")

a = Analysis(  # noqa: F821 — имена PyInstaller подставляются при сборке
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[(str(LEMMAS), "map_overlay/data")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MappersOverlayRedux",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MappersOverlayRedux",
)
