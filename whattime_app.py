import webview
import os
import sys
import json
import copy
import threading
import base64

IS_MAC = sys.platform == 'darwin'
APP_VERSION = '2.1.4'
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

WEBVIEW_STORAGE_PATH = None
if not IS_MAC:
    WEBVIEW_STORAGE_PATH = os.path.join(
        os.environ.get('LOCALAPPDATA', data_dir),
        'WhatTime',
        'WebView2',
    )
    os.makedirs(WEBVIEW_STORAGE_PATH, exist_ok=True)

# ─────────────────────────────────────────
# Windows 전용 상수 및 투명도 유틸
# ─────────────────────────────────────────
if not IS_MAC:
    STARTUP_REG_KEY  = r'Software\Microsoft\Windows\CurrentVersion\Run'
    STARTUP_APP_NAME = 'WhatTime'
    WIN_TITLE        = '지금 몇교시야'
    SINGLE_INSTANCE_MUTEX = 'Local\\whattime-single-instance'
    ERROR_ALREADY_EXISTS = 183
    _single_instance_mutex = None

    class _MARGINS(ctypes.Structure):
        _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                    ('top', ctypes.c_int),  ('bottom', ctypes.c_int)]

    def _ensure_single_instance():
        global _single_instance_mutex
        _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _k32.CreateMutexW.restype = wintypes.HANDLE
        _single_instance_mutex = _k32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
        return ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def _get_hwnd():
        # This function is called from worker/API threads. Accessing the
        # pythonnet-backed WinForms object there can deadlock or crash.
        return windll.user32.FindWindowW(None, WIN_TITLE)

    def _fix_transparency(hwnd):
        m = _MARGINS(-1, -1, -1, -1)
        windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))

    def _apply_windows_transparency():
        hwnd = _get_hwnd()
        if not hwnd:
            return
        try:
            _fix_transparency(hwnd)
        except Exception:
            pass

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
    "comci_school_name": "조암중학교",
    "comci_school_code": 84946,
    "comci_teacher_number": 7,
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

def _ssl_context():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

def _urlopen(req_or_url, timeout=None):
    import urllib.request
    return urllib.request.urlopen(req_or_url, timeout=timeout, context=_ssl_context())

COMCI_API_URL = 'http://comci.net:4082/36179_T'
COMCI_SEARCH_URL = 'http://comci.net:4082/36179'
DEFAULT_COMCI_SCHOOL_CODE = 84946
DEFAULT_COMCI_TEACHER_NUMBER = 7

def _decode_comci_json(raw):
    text = raw.decode('utf-8', errors='replace').strip('\x00 \t\r\n')
    decoder = json.JSONDecoder()
    index = 0
    first = None
    while index < len(text):
        data, end = decoder.raw_decode(text[index:])
        if first is None:
            first = data
        if isinstance(data, dict) and '자료542' in data:
            return data
        index += end
        while index < len(text) and text[index] in '\x00 \t\r\n':
            index += 1
    return first

def search_comci_schools(query):
    import urllib.parse
    import urllib.request
    query = str(query or '').strip()
    if not query:
        raise ValueError('검색할 학교 이름을 입력해 주세요.')

    encoded = urllib.parse.quote(query, encoding='euc-kr', safe='')
    req = urllib.request.Request(
        f'{COMCI_SEARCH_URL}?17384l{encoded}',
        headers={
            'User-Agent': 'WhatTime/' + APP_VERSION,
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'http://comci.net:4082/th',
            'x-requested-with': 'XMLHttpRequest',
        },
    )
    with _urlopen(req, timeout=10) as response:
        data = _decode_comci_json(response.read())

    results = []
    for item in (data or {}).get('학교검색', []):
        if len(item) >= 4 and item[1] != '알림' and item[3]:
            results.append({
                'region': str(item[1]),
                'school_name': str(item[2]),
                'school_code': int(item[3]),
            })
    return results

def _fetch_comci_raw(school_code, date_index=1):
    import urllib.request
    payload = f'73629_{int(school_code)}_0_{int(date_index)}'
    query = base64.b64encode(payload.encode('ascii')).decode('ascii')
    req = urllib.request.Request(
        f'{COMCI_API_URL}?{query}',
        headers={
            'User-Agent': 'WhatTime/' + APP_VERSION,
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'http://comci.net:4082/th',
            'x-requested-with': 'XMLHttpRequest',
        },
    )
    with _urlopen(req, timeout=10) as response:
        data = _decode_comci_json(response.read())
    if not isinstance(data, dict) or '자료542' not in data:
        raise ValueError('학교코드를 확인할 수 없거나 시간표 자료가 없습니다.')
    return data

def fetch_comci_teacher_schedule(school_code=DEFAULT_COMCI_SCHOOL_CODE, teacher_number=DEFAULT_COMCI_TEACHER_NUMBER):
    try:
        school_code = int(school_code)
        teacher_number = int(teacher_number)
    except (TypeError, ValueError):
        raise ValueError('학교코드와 교사 번호는 숫자로 입력해 주세요.')
    if school_code <= 0 or teacher_number <= 0:
        raise ValueError('학교코드와 교사 번호는 1 이상의 숫자여야 합니다.')

    data = _fetch_comci_raw(school_code, 1)
    today_index = int(data.get('오늘r') or 1)
    if today_index != 1:
        data = _fetch_comci_raw(school_code, today_index)

    teachers = data.get('자료446') or []
    teacher_slots = data.get('자료542') or []
    subjects = data.get('자료492') or []
    if teacher_number >= len(teachers) or teacher_number >= len(teacher_slots):
        max_teacher = max(0, min(len(teachers), len(teacher_slots)) - 1)
        raise ValueError(f'교사 번호를 찾을 수 없습니다. 입력 가능한 범위는 1~{max_teacher}입니다.')

    personal = {}
    for day in range(1, 6):
        day_slots = teacher_slots[teacher_number][day] if day < len(teacher_slots[teacher_number]) else []
        entries = []
        for period in range(1, 9):
            raw_code = day_slots[period] if period < len(day_slots) else 0
            changed = isinstance(raw_code, str) and raw_code.startswith('>')
            try:
                code = int(str(raw_code).lstrip('>'))
            except (TypeError, ValueError):
                code = 0

            if code <= 0:
                entries.append({'name': '', 'room': ''})
                continue

            class_code = code % 1000
            subject_index = code // 1000
            subject = subjects[subject_index] if subject_index < len(subjects) else ''
            grade, class_num = divmod(class_code, 100)
            room = f'{grade}-{class_num}' if grade and class_num else ''
            entries.append({
                'name': str(subject).replace('*', ''),
                'room': room,
                'changed': changed,
            })
        personal[str(day)] = entries

    raw_school_name = str(data.get('학교명') or '')
    return {
        'school_code': school_code,
        'school_name': raw_school_name or str(school_code),
        'school_name_hidden': raw_school_name.startswith('컴시간'),
        'teacher_name': teachers[teacher_number],
        'teacher_number': teacher_number,
        'updated_at': data.get('자료244') or '',
        'personal': personal,
    }

def _fetch_latest_release():
    import urllib.request, json
    try:
        req = urllib.request.Request(UPDATE_API_URL, headers={'User-Agent': 'WhatTime/' + APP_VERSION})
        with _urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'_error': str(e)}

def _build_update_result(data):
    if not data or data.get('_error'):
        return {'has_update': False, 'current': APP_VERSION, 'error': data.get('_error') if data else 'no response'}
    latest = data.get('tag_name', '').lstrip('v')
    if not latest:
        return {'has_update': False, 'current': APP_VERSION, 'error': 'release tag not found'}
    if _version_tuple(latest) <= _version_tuple(APP_VERSION):
        return {'has_update': False, 'version': latest, 'current': APP_VERSION}
    asset_name = 'WhatTime-mac.dmg' if IS_MAC else 'whattime.exe'
    url = next((a['browser_download_url'] for a in data.get('assets', []) if a['name'] == asset_name), None)
    if not url:
        return {'has_update': False, 'version': latest, 'current': APP_VERSION, 'error': asset_name + ' not found'}
    return {'has_update': True, 'version': latest, 'url': url, 'current': APP_VERSION}

def _check_update_result():
    try:
        return _build_update_result(_fetch_latest_release())
    except Exception as e:
        return {'has_update': False, 'current': APP_VERSION, 'error': str(e)}

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
        self._font_cache = None
        self._font_loading = False
        self._settings_opening = False
        self._startup_enabled_result = None
        self._update_results = {}

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
        if self._settings_opening:
            return
        if self.settings_window is not None:
            if self.settings_window in webview.windows:
                try:
                    self.settings_window.on_top = True
                except:
                    pass
                return
            else:
                self.settings_window = None

        self._settings_opening = True
        try:
            self.settings_window = webview.create_window(
                title='설정',
                url=SETTINGS_HTML,
                width=480,
                height=720,
                resizable=True,
                js_api=self,
            )
        finally:
            self._settings_opening = False

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

    def get_startup_enabled_async(self, target='settings'):
        self._startup_enabled_result = None
        def run():
            self._startup_enabled_result = bool(self.get_startup_enabled())

        threading.Thread(target=run, daemon=True).start()
        return {'started': True}

    def get_startup_enabled_result(self):
        return self._startup_enabled_result

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

    def _load_system_fonts(self):
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

    def _start_font_load(self):
        if self._font_cache is not None:
            return
        if self._font_loading:
            return

        self._font_loading = True

        def load():
            try:
                fonts = self._load_system_fonts()
            except Exception:
                fonts = []
            self._font_cache = fonts
            self._font_loading = False

        threading.Thread(target=load, daemon=True).start()

    def get_system_fonts(self):
        if self._font_cache is not None:
            return self._font_cache
        self._start_font_load()
        return []

    def get_system_fonts_async(self, target='settings'):
        self._start_font_load()
        return {'started': True}

    def get_schedule(self):
        return load_schedule()

    def save_schedule(self, data):
        save_schedule(data)
        def _do():
            main_window.evaluate_js('reloadSchedule()')
        threading.Timer(0.05, _do).start()
        return True

    def fetch_comci_schedule(self, school_code, teacher_number):
        try:
            return {'ok': True, **fetch_comci_teacher_schedule(school_code, teacher_number)}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def search_comci_schools(self, query):
        try:
            return {'ok': True, 'schools': search_comci_schools(query)}
        except Exception as e:
            return {'ok': False, 'error': str(e), 'schools': []}

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

    def refresh_transparency(self):
        if not IS_MAC:
            _apply_windows_transparency()
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
        return _check_update_result()

    def check_update_async(self, target='main'):
        self._update_results[target] = None
        def run():
            self._update_results[target] = _check_update_result()

        threading.Thread(target=run, daemon=True).start()
        return {'started': True, 'current': APP_VERSION}

    def get_update_result(self, target='main'):
        return self._update_results.get(target)

    def install_update(self, url):
        import tempfile, urllib.request, shutil, subprocess
        try:
            tmp = tempfile.mkdtemp()
            if IS_MAC:
                dmg_path = os.path.join(tmp, 'WhatTime-mac.dmg')
                with _urlopen(url) as resp, open(dmg_path, 'wb') as f:
                    shutil.copyfileobj(resp, f)
                mount_point = os.path.join(tmp, 'mnt')
                os.makedirs(mount_point, exist_ok=True)
                subprocess.run(['hdiutil', 'attach', dmg_path, '-mountpoint', mount_point, '-nobrowse', '-quiet'], check=True)
                new_app_tmp = os.path.join(tmp, '지금 몇교시야.app')
                subprocess.run(['cp', '-R', os.path.join(mount_point, '지금 몇교시야.app'), new_app_tmp], check=True)
                subprocess.run(['hdiutil', 'detach', mount_point, '-quiet'])
                if not getattr(sys, 'frozen', False):
                    return False
                app_path = os.path.normpath(os.path.join(os.path.dirname(sys.executable), '..', '..'))
                script = f"#!/bin/bash\nsleep 2\nrm -rf '{app_path}'\ncp -R '{new_app_tmp}' '{app_path}'\nxattr -dr com.apple.quarantine '{app_path}' 2>/dev/null || true\nopen '{app_path}'\n"
                script_path = os.path.join(tmp, 'update.sh')
                with open(script_path, 'w') as f:
                    f.write(script)
                os.chmod(script_path, 0o755)
                subprocess.Popen(['/bin/bash', script_path])
            else:
                exe_path = os.path.join(tmp, 'whattime_new.exe')
                with _urlopen(url) as resp, open(exe_path, 'wb') as f:
                    shutil.copyfileobj(resp, f)
                if not getattr(sys, 'frozen', False):
                    return False
                current_exe = sys.executable
                app_dir = os.path.dirname(current_exe)
                log_path = os.path.join(tempfile.gettempdir(), 'whattime_update.log')

                def ps_quote(value):
                    return "'" + value.replace("'", "''") + "'"

                ps1 = (
                    "$ErrorActionPreference = 'Continue'\n"
                    "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'\n"
                    f"$src = {ps_quote(exe_path)}\n"
                    f"$dst = {ps_quote(current_exe)}\n"
                    f"$appDir = {ps_quote(app_dir)}\n"
                    f"$log = {ps_quote(log_path)}\n"
                    "function Write-UpdateLog($message) {\n"
                    "  $line = ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message)\n"
                    "  Add-Content -LiteralPath $log -Value $line -Encoding UTF8\n"
                    "}\n"
                    "Write-UpdateLog 'update helper started'\n"
                    "Start-Sleep -Seconds 2\n"
                    "$copied = $false\n"
                    "for ($i = 1; $i -le 30; $i++) {\n"
                    "  try {\n"
                    "    Copy-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop\n"
                    "    Write-UpdateLog ('copy succeeded on attempt {0}' -f $i)\n"
                    "    $copied = $true\n"
                    "    break\n"
                    "  } catch {\n"
                    "    Write-UpdateLog ('copy failed on attempt {0}: {1}' -f $i, $_.Exception.Message)\n"
                    "    Start-Sleep -Seconds 1\n"
                    "  }\n"
                    "}\n"
                    "if (-not $copied) {\n"
                    "  Write-UpdateLog 'copy never succeeded; restarting existing app'\n"
                    "  try {\n"
                    "    Start-Process -FilePath $dst -WorkingDirectory $appDir\n"
                    "  } catch {\n"
                    "    Write-UpdateLog ('existing app restart failed: {0}' -f $_.Exception.Message)\n"
                    "  }\n"
                    "  exit 1\n"
                    "}\n"
                    "try {\n"
                    "  Start-Sleep -Milliseconds 800\n"
                    "  Write-UpdateLog 'starting updated app'\n"
                    "  Start-Process -FilePath $dst -WorkingDirectory $appDir\n"
                    "} catch {\n"
                    "  Write-UpdateLog ('restart failed: {0}' -f $_.Exception.Message)\n"
                    "}\n"
                    "Start-Sleep -Seconds 1\n"
                    "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
                )
                ps1_path = os.path.join(tmp, 'update.ps1')
                with open(ps1_path, 'w', encoding='utf-8') as f:
                    f.write(ps1)
                env = os.environ.copy()
                env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
                subprocess.Popen(
                    ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ps1_path],
                    creationflags=0x08000000 | 0x00000200,
                    cwd=app_dir,
                    env=env,
                    close_fds=True,
                )
            # 업데이트 대상 파일 잠금을 확실히 해제한다. Windows에서 창만
            # destroy하면 설정 창/WebView 프로세스가 남아 exe 교체가 실패할 수 있다.
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

if not IS_MAC and not _ensure_single_instance():
    sys.exit(0)

api = Api()

main_window = webview.create_window(
    title='지금 몇교시야',
    url=MAIN_HTML,
    width=340,
    height=700,
    resizable=True,
    frameless=True,
    transparent=True,
    background_color='#000000',
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
        def apply_later():
            import time
            for delay in (0.05, 0.2, 0.6, 1.2):
                time.sleep(delay)
                _apply_windows_transparency()
            hwnd = _get_hwnd()
            if hwnd:
                _start_restore_watcher(hwnd)
        threading.Thread(target=apply_later, daemon=True).start()

    main_window.events.shown += on_window_shown

if __name__ == '__main__':
    if IS_MAC:
        webview.start()
    else:
        webview.start(gui='edgechromium', private_mode=False, storage_path=WEBVIEW_STORAGE_PATH)
