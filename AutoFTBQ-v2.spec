# -*- mode: python ; coding: utf-8 -*-

import os

a = Analysis(
    ['v2_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('autoftbq_v2/skills', 'autoftbq_v2/skills'),
        ('human_style_corpus.json.gz', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter'],
    noarchive=False,
    optimize=0,
)

# Qt 6 uses the Windows ICU forwarding DLL. Some developer shells add a
# Poppler directory to PATH; PyInstaller may then collect Poppler's unrelated
# ICU implementation and shadow the system DLL, causing QtGui error 127 at
# startup. Never ship those environment-derived binaries.
a.binaries = type(a.binaries)(
    entry for entry in a.binaries
    if os.path.basename(entry[0]).lower() not in {"icuuc.dll", "icudt78.dll"}
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='AutoFTBQ-Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='AutoFTBQ-Studio',
)
