# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

_spec_dir = Path(SPECPATH).resolve()
REPO_ROOT = _spec_dir.parent.parent if _spec_dir.name == "backend" else _spec_dir

a = Analysis(
    [str(REPO_ROOT / 'src' / 'backend' / 'agent.py')],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / 'src' / 'backend')],
    binaries=[],
    datas=[
        (str(REPO_ROOT / 'assets'), 'assets'),
        (str(REPO_ROOT / 'icons'), 'icons'),
        (str(REPO_ROOT / 'VERSION'), '.'),
    ],
    hiddenimports=[
        'requests',
        'minecraft_launcher_lib',
        'PIL',
        'PIL.Image',
        'nlc',
        'nlc.cdc_engine',
        'nlc.core',
        'nlc.core.skins',
        'nlc.core.launch',
        'nlc.core.versions',
        'nlc.core.skin_renderer',
        'nlc.core.discord_rpc',
        'pypresence',
        'nlc.net',
        'nlc.net.skin_server',
        'nlc.net.mod_icons',
        'nlc.storage',
        'nlc.storage.config',
        'nlc.version',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
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
    name='agent',
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
)
