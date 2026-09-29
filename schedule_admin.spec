# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_data_files

is_mac = sys.platform == 'darwin'
a = Analysis(
    ['schedule_admin.py'], pathex=[], binaries=[],
    datas=[('schedule_admin.html', '.')] + collect_data_files('certifi'),
    hiddenimports=['webview', 'certifi', 'bottle', 'proxy_tools', 'keyring.backends.macOS' if is_mac else 'keyring.backends.Windows'] + (
        ['webview.platforms.cocoa', 'webview.js', 'objc', 'Foundation', 'AppKit', 'WebKit', 'Quartz'] if is_mac else []),
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
if is_mac:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='WhatTime-Schedule-Admin',
              debug=False, strip=False, upx=True, console=False)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name='WhatTime-Schedule-Admin-mac')
    app = BUNDLE(coll, name='특별시정 관리자.app', icon='icon.icns',
                 bundle_identifier='com.whattime.schedule-admin')
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='WhatTime-Schedule-Admin',
              debug=False, strip=False, upx=True, console=False, icon='icon.ico')
