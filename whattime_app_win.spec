# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['whattime_app.py'],
    pathex=[],
    binaries=[],
    datas=[('lesson_mapping.js', '.'), ('lesson_mapping_editor.js', '.'), ('subscription_confirm.js', '.'), ('whattime.html', '.'), ('settings.html', '.'), ('progress_popup.html', '.'), ('progress_history.html', '.'), ('lesson_end.html', '.'), ('powerpoint_confirm.html', '.'), ('desktop_reminder.html', '.')],
    hiddenimports=[],
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
    name='whattime',
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
    icon=['icon.ico'],
)
