# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


a = Analysis(
    ['whattime_app.py'],
    pathex=[],
    binaries=[],
    datas=[('whattime.html', '.'), ('settings.html', '.'), ('calendar.png', '.')] + collect_data_files('certifi'),
    hiddenimports=[
        'webview',
        'webview.platforms.edgechromium',
        'webview.js',
        'certifi',
        'bottle',
        'proxy_tools',
        'clr',
        'System',
        'System.Windows.Forms',
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
    name='WhatTime',
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
    icon='calendar.png',
)
