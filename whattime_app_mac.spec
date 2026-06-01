# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


a = Analysis(
    ['whattime_app.py'],
    pathex=[],
    binaries=[],
    datas=[('whattime.html', '.'), ('settings.html', '.'), ('calendar.png', '.')] + collect_data_files('certifi'),
    hiddenimports=[
        'webview',
        'webview.platforms.cocoa',
        'webview.js',
        'certifi',
        'objc',
        'Foundation',
        'AppKit',
        'WebKit',
        'Quartz',
        'bottle',
        'proxy_tools',
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
    [],
    exclude_binaries=True,
    name='whattime_app_mac',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='whattime_app_mac',
)
app = BUNDLE(
    coll,
    name='지금 몇교시야.app',
    icon='icon.icns',
    bundle_identifier='com.whattime.app',
    info_plist={
        'CFBundleDisplayName': '지금 몇교시야',
        'CFBundleName': '지금 몇교시야',
    },
)
