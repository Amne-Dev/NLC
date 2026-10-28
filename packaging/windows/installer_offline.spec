# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parent.parent

a = Analysis(
    [str(Path(SPECPATH) / 'installer_app.py')],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / 'src' / 'backend'), str(Path(SPECPATH))],
    binaries=[],
    datas=[
        (str(REPO_ROOT / 'logo.ico'), '.'),
        (str(REPO_ROOT / 'logo.png'), '.'),
        (str(Path(SPECPATH) / 'config_healer.py'), '.'),
        (str(REPO_ROOT / 'VERSION'), '.'),
        (str(REPO_ROOT / 'logo.ico'), 'payload'),
        (str(REPO_ROOT / 'logo.png'), 'payload'),
        (str(REPO_ROOT / 'dist' / 'NyLuna.exe'), 'payload'),

        (str(REPO_ROOT / 'dist' / 'agent.exe'), 'payload'),
    ] + ([(str(REPO_ROOT / 'dist' / 'libunwind.dll'), 'payload')] if (REPO_ROOT / 'dist' / 'libunwind.dll').is_file() else []) + [
        (str(REPO_ROOT / 'icons'), 'payload/icons'),
        (str(REPO_ROOT / 'wallpapers'), 'payload/wallpapers'),
        (str(REPO_ROOT / 'skins'), 'payload/skins'),
        (str(REPO_ROOT / 'assets'), 'payload/assets'),
    ],
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageTk', 'nlc.version'],
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
    name='NLCSetup-Offline',
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

