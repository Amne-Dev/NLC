# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
if (spec_dir / 'packaging' / 'windows').is_dir():
    REPO_ROOT = spec_dir
    PKG_DIR = spec_dir / 'packaging' / 'windows'
else:
    REPO_ROOT = spec_dir.parent.parent
    PKG_DIR = spec_dir

a = Analysis(
    [str(PKG_DIR / 'installer_app.py')],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / 'src' / 'backend'), str(PKG_DIR)],
    binaries=[],
    datas=[
        (str(REPO_ROOT / 'logo.ico'), '.'),
        (str(REPO_ROOT / 'logo.png'), '.'),
        (str(PKG_DIR / 'config_healer.py'), '.'),
        (str(REPO_ROOT / 'VERSION'), '.'),
    ],
    hiddenimports=[
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'requests',
        'cryptography',
        'nlc.version',
        'nlc.cdc_engine',
        'nlc.core.updater',
        'nlc.update_engine',
        'nlc.update_keys',
    ],
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

