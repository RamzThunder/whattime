import webview
import os
import sys
import json
import copy
import threading

IS_MAC = sys.platform == 'darwin'
APP_VERSION = '1.9.1'
UPDATE_API_URL = 'https://api.github.com/repos/RamzThunder/whattime-releases/releases/latest'

# ─────────────────────────────────────────
# 플랫폼별 import
# ─────────────────────────────────────────
if IS_MAC:
    import plistlib
else:
    import winreg
    import ctypes
    from ctypes import windll, wintypes

# ─────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

if getattr(sys, 'frozen', False):
    if IS_MAC:
        # 앱 업데이트 시에도 데이터 유지: 번들 외부의 사용자 디렉토리에 저장
        data_dir = os.path.expanduser('~/Library/Application Support/WhatTime')
        os.makedirs(data_dir, exist_ok=True)
    else:
        data_dir = os.path.dirname(sys.executable)
else:
    data_dir = base_dir

SCHEDULE_PATH      = os.path.join(data_dir, 'schedule.json')
USER_DEFAULT_PATH  = os.path.join(data_dir, 'user_default.json')
MAIN_HTML          = os.path.join(base_dir, 'whattime.html')
SETTINGS_HTML      = os.path.join(base_dir, 'settings.html')

# ─────────────────────────────────────────
# Windows 전용 상수 및 투명도 유틸
# ─────────────────────────────────────────
if not IS_MAC:
    STARTUP_REG_KEY  = r'Software\Microsoft\Windows\CurrentVersion\Run'
    STARTUP_APP_NAME = 'WhatTime'
    WIN_TITLE        = '지금 몇교시야?'

    class _MARGINS(ctypes.Structure):
        _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                    ('top', ctypes.c_int),  ('bottom', ctypes.c_int)]

    def _get_hwnd():
        try:
            return main_window.native.Handle.ToInt32()
        except Exception:
            return windll.user32.FindWindowW(None, WIN_TITLE)

    def _fix_transparency(hwnd):
        m = _MARGINS(-1, -1, -1, -1)
        windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))

# ─────────────────────────────────────────
# 기본 시정 데이터
# ─────────────────────────────────────────
DEFAULT_SCHEDULE = {
    "full": [
        {"name": "수업 전",            "start": "08:00", "end": "08:35"},
        {"name": "1교시",              "start": "08:40", "end": "09:25"},
        {"name": "2교시",              "start": "09:35", "end": "10:20"},
        {"name": "3교시",              "start": "10:30", "end": "11:15"},
        {"name": "4교시",              "start": "11:25", "end": "12:10"},
        {"name": "점심 (1학년 5교시)", "start": "12:15", "end": "13:00"},
        {"name": "5교시 (1학년 점심)", "start": "13:00", "end": "13:45"},
        {"name": "6교시",              "start": "13:50", "end": "14:35"},
        {"name": "7교시",              "start": "14:45", "end": "15:30"},
        {"name": "수업 끝^-^",         "start": "15:30", "end": "16:20"}
    ],
    "short": [
        {"name": "수업 전",            "start": "08:00", "end": "08:35"},
        {"name": "1교시",              "start": "08:40", "end": "09:25"},
        {"name": "2교시",              "start": "09:35", "end": "10:20"},
        {"name": "3교시",              "start": "10:30", "end": "11:15"},
        {"name": "4교시",              "start": "11:25", "end": "12:10"},
        {"name": "점심 (1학년 5교시)", "start": "12:15", "end": "13:00"},
        {"name": "5교시 (1학년 점심)", "start": "13:00", "end": "13:45"},
        {"name": "6교시",              "start": "13:50", "end": "14:35"},
        {"name": "수업 끝^-^",         "start": "14:35", "end": "16:20"}
    ],
    "short_days": [3, 5],
    "rest_days": [0, 6],
    "rest_schedules": {"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
    "personal": {"1": [], "2": [], "3": [], "4": [], "5": []},
    "end_text": "˚˖𓍢ִִ໋˚˖𓍢ִ✧˚.오늘 일정 종료˚˖𓍢ִִ໋˚˖𓍢ִ✧˚.",
    "rest_status_text": "학교 생각을 왜 하지",
    "rest_timer_prefix": "출근까지",
    "bg_color": "#ffffff",
    "active_color": "#000000",
    "inactive_color": "#f1f1ef",
    "countdown_color": "#2f6df6",
    "custom_colors": [],
    "custom_colors_inactive": [],
    "custom_colors_countdown": [],
    "custom_colors_no_countdown": [],
    "custom_colors_bg": [],
    "no_countdown_color": "#787774",
    "font_family": "",
    "font_bold": False,
    "font_scale": 1.0,
    "has_bg": True,
    "opacity": 100,
    "show_ms": True,
    "bell_alert_enabled": False,
    "bell_alert_color": "#ff3b30",
    "custom_colors_bell_alert": []
}

def _version_tuple(v):
    try:
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0,)

def _fetch_latest_release():
    import urllib.request, json
    try:
        req = urllib.request.Request(UPDATE_API_URL, headers={'User-Agent': 'WhatTime/' + APP_VERSION})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None

def load_schedule():
    if os.path.exists(SCHEDULE_PATH):
        try:
            with open(SCHEDULE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return copy.deepcopy(DEFAULT_SCHEDULE)

def save_schedule(data):
    with open(SCHEDULE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────
# JS API
# ─────────────────────────────────────────
class Api:
    def __init__(self):
        self.settings_window = None
        self._pinned = False

    def toggle_on_top(self, is_pinned):
        self._pinned = is_pinned
        def _do():
            main_window.on_top = is_pinned
        threading.Timer(0, _do).start()

    def set_mini_mode(self, is_mini):
        def _do():
            if is_mini:
                main_window.resize(320, 130)
            else:
                main_window.resize(340, 700)
        threading.Timer(0, _do).start()

    def open_settings(self):
        if self.settings_window is not None:
            if self.settings_window in webview.windows:
                try:
                    self.settings_window.on_top = True
                except:
                    pass
                return
            else:
                self.settings_window = None

        self.settings_window = webview.create_window(
            title='시정 설정',
            url=SETTINGS_HTML,
            width=480,
            height=720,
            resizable=True,
            js_api=self,
        )

        def on_closed():
            self.settings_window = None
        self.settings_window.events.closed += on_closed

    def get_startup_enabled(self):
        if IS_MAC:
            plist_path = os.path.expanduser('~/Library/LaunchAgents/com.whattime.app.plist')
            return os.path.exists(plist_path)
        else:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ)
                winreg.QueryValueEx(key, STARTUP_APP_NAME)
                winreg.CloseKey(key)
                return True
            except OSError:
                return False

    def set_startup(self, enabled):
        if IS_MAC:
            plist_path = os.path.expanduser('~/Library/LaunchAgents/com.whattime.app.plist')
            if enabled:
                if getattr(sys, 'frozen', False):
                    program = sys.executable
                else:
                    program = os.path.abspath(__file__)
                plist = {
                    'Label': 'com.whattime.app',
                    'ProgramArguments': [program],
                    'RunAtLoad': True,
                }
                os.makedirs(os.path.dirname(plist_path), exist_ok=True)
                with open(plist_path, 'wb') as f:
                    plistlib.dump(plist, f)
            else:
                if os.path.exists(plist_path):
                    os.remove(plist_path)
            return True
        else:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE)
                try:
                    if enabled:
                        if getattr(sys, 'frozen', False):
                            program = sys.executable
                        else:
                            program = f'pythonw "{os.path.abspath(__file__)}"'
                        winreg.SetValueEx(key, STARTUP_APP_NAME, 0, winreg.REG_SZ, program)
                    else:
                        try:
                            winreg.DeleteValue(key, STARTUP_APP_NAME)
                        except FileNotFoundError:
                            pass
                finally:
                    winreg.CloseKey(key)
            except Exception:
                return False
            return True

    def get_system_fonts(self):
        if IS_MAC:
            try:
                from AppKit import NSFontManager
                fonts = sorted(NSFontManager.sharedFontManager().availableFontFamilies())
                return list(fonts)
            except:
                return []
        else:
            try:
                class LOGFONTW(ctypes.Structure):
                    _fields_ = [
                        ('lfHeight',         ctypes.c_long),
                        ('lfWidth',          ctypes.c_long),
                        ('lfEscapement',     ctypes.c_long),
                        ('lfOrientation',    ctypes.c_long),
                        ('lfWeight',         ctypes.c_long),
                        ('lfItalic',         ctypes.c_byte),
                        ('lfUnderline',      ctypes.c_byte),
                        ('lfStrikeOut',      ctypes.c_byte),
                        ('lfCharSet',        ctypes.c_byte),
                        ('lfOutPrecision',   ctypes.c_byte),
                        ('lfClipPrecision',  ctypes.c_byte),
                        ('lfQuality',        ctypes.c_byte),
                        ('lfPitchAndFamily', ctypes.c_byte),
                        ('lfFaceName',       ctypes.c_wchar * 32),
                    ]

                class ENUMLOGFONTEXW(ctypes.Structure):
                    _fields_ = [
                        ('elfLogFont',  LOGFONTW),
                        ('elfFullName', ctypes.c_wchar * 64),
                        ('elfStyle',    ctypes.c_wchar * 32),
                        ('elfScript',   ctypes.c_wchar * 32),
                    ]

                families = set()
                FONTENUMPROC = ctypes.WINFUNCTYPE(
                    ctypes.c_int,
                    ctypes.POINTER(ENUMLOGFONTEXW),
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.c_long
                )

                def _cb(lpelfe, *_):
                    name = lpelfe.contents.elfLogFont.lfFaceName
                    if name and not name.startswith('@'):
                        families.add(name)
                    return 1

                hdc = windll.user32.GetDC(0)
                lf = LOGFONTW()
                lf.lfCharSet = 1  # DEFAULT_CHARSET
                proc = FONTENUMPROC(_cb)
                windll.gdi32.EnumFontFamiliesExW(hdc, ctypes.byref(lf), proc, 0, 0)
                windll.user32.ReleaseDC(0, hdc)
                return sorted(families)
            except:
                return []

    def get_schedule(self):
        return load_schedule()

    def save_schedule(self, data):
        save_schedule(data)
        def _do():
            main_window.evaluate_js('reloadSchedule()')
        threading.Timer(0.05, _do).start()
        return True

    def set_preview_offset(self, offset_seconds):
        def _do():
            main_window.evaluate_js(f'setPreviewOffset({int(offset_seconds)})')
        threading.Timer(0, _do).start()
        return True

    def clear_preview_offset(self):
        def _do():
            main_window.evaluate_js('clearPreviewOffset()')
        threading.Timer(0, _do).start()
        return True

    def preview_theme_color(self, key, color):
        import re
        if key not in ('active', 'inactive', 'countdown', 'no_countdown', 'bg', 'bell_alert'):
            return False
        if key == 'bg' and color == '':
            def _do():
                main_window.evaluate_js("applyThemeColorByKey('bg','')")
            threading.Timer(0, _do).start()
            return True
        if not re.match(r'^#[0-9a-fA-F]{6}$', color):
            return False
        esc_key = key.replace("'", "\\'")
        esc_color = color.replace("'", "\\'")
        def _do():
            main_window.evaluate_js(f"applyThemeColorByKey('{esc_key}','{esc_color}')")
        threading.Timer(0, _do).start()
        return True

    def preview_color(self, color):
        return self.preview_theme_color('active', color)

    def preview_font(self, font):
        import re
        if font and re.search(r'[<>"\';&]', font):
            return False
        escaped = (font or '').replace("'", "\\'")
        def _do():
            main_window.evaluate_js(f"applyThemeFont('{escaped}')")
        threading.Timer(0, _do).start()
        return True

    def preview_bold(self, bold):
        val = 'true' if bold else 'false'
        def _do():
            main_window.evaluate_js(f"applyThemeBold({val})")
        threading.Timer(0, _do).start()
        return True

    def preview_font_scale(self, scale):
        try:
            scale = max(0.5, min(2.0, float(scale)))
        except:
            return False
        def _do():
            main_window.evaluate_js(f'applyFontScale({scale})')
        threading.Timer(0, _do).start()
        return True

    # Mac 버전 HTML과의 호환성을 위한 별칭
    def preview_font_size(self, scale):
        return self.preview_font_scale(scale)

    def minimize_window(self):
        if IS_MAC:
            minimize_fn = getattr(main_window, 'minimize', None)
            if minimize_fn:
                threading.Timer(0, minimize_fn).start()
        else:
            threading.Timer(0, lambda: windll.user32.ShowWindow(
                _get_hwnd(), 6  # SW_MINIMIZE
            )).start()

    def close_app(self):
        if IS_MAC:
            # destroy()는 macOS에서 데드락 발생 가능
            threading.Timer(0.1, os._exit, args=[0]).start()
        else:
            threading.Timer(0, main_window.destroy).start()

    def start_resize(self, direction):
        import time
        if IS_MAC:
            return
        hwnd = windll.user32.FindWindowW(None, WIN_TITLE)
        if not hwnd:
            return
        pt = wintypes.POINT()
        windll.user32.GetCursorPos(ctypes.byref(pt))
        rect = wintypes.RECT()
        windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        sx, sy = pt.x, pt.y
        sw = rect.right  - rect.left
        sh = rect.bottom - rect.top
        wx, wy = rect.left, rect.top
        MIN_W, MIN_H = 200, 100
        SWP = 0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE

        def track():
            while windll.user32.GetAsyncKeyState(0x01) & 0x8000:
                cur = wintypes.POINT()
                windll.user32.GetCursorPos(ctypes.byref(cur))
                dx, dy = cur.x - sx, cur.y - sy
                nx, ny, nw, nh = wx, wy, sw, sh
                if 'left' in direction:
                    nw = max(MIN_W, sw - dx); nx = wx + (sw - nw)
                elif 'right' in direction:
                    nw = max(MIN_W, sw + dx)
                if 'top' in direction:
                    nh = max(MIN_H, sh - dy); ny = wy + (sh - nh)
                elif 'bottom' in direction:
                    nh = max(MIN_H, sh + dy)
                windll.user32.SetWindowPos(hwnd, None, nx, ny, nw, nh, SWP)
                time.sleep(0.01)

        threading.Thread(target=track, daemon=True).start()

    def preview_opacity(self, val):
        try:
            val = max(10, min(100, int(val)))
        except Exception:
            return False
        def _do():
            main_window.evaluate_js(f'applyOpacity({val})')
        threading.Timer(0, _do).start()
        return True

    def preview_show_ms(self, val):
        v = 'true' if val else 'false'
        def _do():
            main_window.evaluate_js(f'applyShowMs({v})')
        threading.Timer(0, _do).start()
        return True

    def export_data(self):
        if not self.settings_window:
            return False
        try:
            result = self.settings_window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename='schedule_backup.json',
                file_types=('JSON files (*.json)', 'All files (*.*)')
            )
            if not result:
                return False
            import shutil
            path = result[0] if isinstance(result, (list, tuple)) else result
            shutil.copy2(SCHEDULE_PATH, path)
            return True
        except Exception:
            return False

    def import_data(self):
        if not self.settings_window:
            return False
        try:
            result = self.settings_window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=('JSON files (*.json)', 'All files (*.*)')
            )
            if not result:
                return False
            path = result[0] if isinstance(result, (list, tuple)) else result
            with open(path, 'r', encoding='utf-8') as f:
                new_data = json.load(f)
            save_schedule(new_data)
            def _do():
                main_window.evaluate_js('reloadSchedule()')
            threading.Timer(0.05, _do).start()
            return True
        except Exception:
            return False

    def set_as_default(self):
        try:
            current = load_schedule()
            with open(USER_DEFAULT_PATH, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def reset_data(self):
        if os.path.exists(USER_DEFAULT_PATH):
            try:
                with open(USER_DEFAULT_PATH, 'r', encoding='utf-8') as f:
                    default_data = json.load(f)
            except Exception:
                default_data = copy.deepcopy(DEFAULT_SCHEDULE)
        else:
            default_data = copy.deepcopy(DEFAULT_SCHEDULE)
        save_schedule(default_data)
        def _do():
            main_window.evaluate_js('reloadSchedule()')
        threading.Timer(0.05, _do).start()
        return True

    def check_update(self):
        data = _fetch_latest_release()
        if not data:
            return {'has_update': False, 'current': APP_VERSION}
        latest = data.get('tag_name', '').lstrip('v')
        if not latest:
            return {'has_update': False, 'current': APP_VERSION}
        if _version_tuple(latest) <= _version_tuple(APP_VERSION):
            return {'has_update': False, 'version': latest, 'current': APP_VERSION}
        asset_name = 'WhatTime-mac.dmg' if IS_MAC else 'WhatTime.exe'
        url = next((a['browser_download_url'] for a in data.get('assets', []) if a['name'] == asset_name), None)
        if not url:
            return {'has_update': False, 'version': latest, 'current': APP_VERSION}
        return {'has_update': True, 'version': latest, 'url': url, 'current': APP_VERSION}

    def install_update(self, url):
        import tempfile, urllib.request, shutil, subprocess
        try:
            tmp = tempfile.mkdtemp()
            if IS_MAC:
                dmg_path = os.path.join(tmp, 'WhatTime-mac.dmg')
                with urllib.request.urlopen(url) as resp, open(dmg_path, 'wb') as f:
                    shutil.copyfileobj(resp, f)
                mount_point = os.path.join(tmp, 'mnt')
                os.makedirs(mount_point, exist_ok=True)
                subprocess.run(['hdiutil', 'attach', dmg_path, '-mountpoint', mount_point, '-nobrowse', '-quiet'], check=True)
                new_app_tmp = os.path.join(tmp, 'WhatTime.app')
                subprocess.run(['cp', '-R', os.path.join(mount_point, 'WhatTime.app'), new_app_tmp], check=True)
                subprocess.run(['hdiutil', 'detach', mount_point, '-quiet'])
                if not getattr(sys, 'frozen', False):
                    return False
                app_path = os.path.normpath(os.path.join(os.path.dirname(sys.executable), '..', '..', '..'))
                script = f"#!/bin/bash\nsleep 2\nrm -rf '{app_path}'\ncp -R '{new_app_tmp}' '{app_path}'\nopen '{app_path}'\n"
                script_path = os.path.join(tmp, 'update.sh')
                with open(script_path, 'w') as f:
                    f.write(script)
                os.chmod(script_path, 0o755)
                subprocess.Popen(['/bin/bash', script_path])
            else:
                exe_path = os.path.join(tmp, 'WhatTime_new.exe')
                with urllib.request.urlopen(url) as resp, open(exe_path, 'wb') as f:
                    shutil.copyfileobj(resp, f)
                if not getattr(sys, 'frozen', False):
                    return False
                current_exe = sys.executable
                bat = f'@echo off\nping 127.0.0.1 -n 3 >nul\ncopy /y "{exe_path}" "{current_exe}"\nstart "" "{current_exe}"\ndel "%~f0"\n'
                bat_path = os.path.join(tmp, 'update.bat')
                with open(bat_path, 'w') as f:
                    f.write(bat)
                subprocess.Popen(['cmd', '/c', bat_path], creationflags=0x08000000)
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return True
        except Exception:
            return False

    def close_settings(self):
        if self.settings_window:
            try:
                self.settings_window.destroy()
            except:
                pass
            self.settings_window = None

api = Api()

main_window = webview.create_window(
    title='지금 몇교시야?',
    url=MAIN_HTML,
    width=340,
    height=700,
    resizable=True,
    frameless=True,
    transparent=True,
    on_top=False,
    x=30,
    y=30,
    js_api=api,
)

# ─────────────────────────────────────────
# Windows: minimize→restore 후 투명도 복구
# ─────────────────────────────────────────
if not IS_MAC:
    def _start_restore_watcher(hwnd):
        import time
        prev_iconic = False
        def watch():
            nonlocal prev_iconic
            while windll.user32.IsWindow(hwnd):
                iconic = bool(windll.user32.IsIconic(hwnd))
                if prev_iconic and not iconic:
                    time.sleep(0.1)
                    _fix_transparency(hwnd)
                prev_iconic = iconic
                time.sleep(0.25)
        threading.Thread(target=watch, daemon=True).start()

    def on_window_shown():
        import time
        time.sleep(0.15)
        hwnd = _get_hwnd()
        if hwnd:
            _fix_transparency(hwnd)
            _start_restore_watcher(hwnd)

    main_window.events.shown += on_window_shown

if __name__ == '__main__':
    if IS_MAC:
        webview.start()
    else:
        webview.start(gui='edgechromium')
