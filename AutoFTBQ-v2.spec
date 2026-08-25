# -*- mode: python ; coding: utf-8 -*-

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
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AutoFTBQ-v2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
