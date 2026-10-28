# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parent.parent

a = Analysis(
    [str(Path(SPECPATH) / 'installer_app.py')],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / 'src' / 'backend')],
    binaries=[],
    datas=[
        (str(REPO_ROOT / 'logo.ico'), '.'),
        (str(REPO_ROOT / 'logo.png'), '.'),
        (str(REPO_ROOT / 'logo.ico'), 'payload'),
        (str(REPO_ROOT / 'logo.png'), 'payload'),
        (str(REPO_ROOT / 'dist' / 'NyLuna.exe'), 'payload'),
        (str(REPO_ROOT / 'dist' / 'agent.exe'), 'payload'),
    ],
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageTk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='NLCSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(REPO_ROOT / 'logo.ico')],
)
