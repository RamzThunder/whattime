import webview
import os
import sys
import json
import copy
import re
import threading
import base64
import datetime
import hashlib
import subprocess
import tempfile

IS_MAC = sys.platform == 'darwin'
APP_VERSION = '2.2.3'
UPDATE_API_URL = 'https://api.github.com/repos/RamzThunder/whattime-releases/releases/latest'

# ─────────────────────────────────────────
# 플랫폼별 import
# ─────────────────────────────────────────
if IS_MAC:
    import plistlib
    from AppKit import NSWorkspace
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
PROGRESS_PATH      = os.path.join(data_dir, 'lesson_progress.json')
PROGRESS_IMAGE_DIR = os.path.join(data_dir, 'lesson_progress_images')
PROGRESS_LOCK      = threading.RLock()
MAIN_HTML          = os.path.join(base_dir, 'whattime.html')
SETTINGS_HTML      = os.path.join(base_dir, 'settings.html')
PROGRESS_HTML      = os.path.join(base_dir, 'progress_popup.html')
PROGRESS_HISTORY_HTML = os.path.join(base_dir, 'progress_history.html')
LESSON_END_HTML    = os.path.join(base_dir, 'lesson_end.html')
POWERPOINT_CONFIRM_HTML = os.path.join(base_dir, 'powerpoint_confirm.html')

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

    def _patch_edgechromium_transparency():
        from webview.platforms import edgechromium

        original_edgechrome = edgechromium.EdgeChrome

        class WhatTimeEdgeChrome(original_edgechrome):
            def _apply_transparency(self):
                if self.pywebview_window.transparent:
                    self.form.BackColor = edgechromium.Color.Black
                    self.webview.DefaultBackgroundColor = edgechromium.Color.Transparent

            def on_webview_ready(self, sender, args):
                result = super().on_webview_ready(sender, args)
                if args.IsSuccess:
                    self._apply_transparency()
                return result

            def on_navigation_completed(self, sender, args):
                result = super().on_navigation_completed(sender, args)
                self._apply_transparency()
                return result

        edgechromium.EdgeChrome = WhatTimeEdgeChrome

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
    "special": [],
    "special_schedules": [],
    "special_schedule_enabled": False,
    "special_schedule_opt_in_version": 1,
    "seven_period_days": [1, 2, 4],
    "special_dates": [],
    "rest_days": [0, 6],
    "rest_schedules": {"0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": []},
    "personal": {"1": [], "2": [], "3": [], "4": [], "5": []},
    "comci_school_name": "",
    "comci_school_code": None,
    "comci_teacher_number": None,
    "comci_joam_first_grade_fifth_period": False,
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
    "custom_colors_bell_alert": [],
    "progress_auto_save": True,
    "progress_auto_capture": True,
    "quit_powerpoint_on_lesson_end": False
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
DEFAULT_COMCI_SCHOOL_CODE = None
DEFAULT_COMCI_TEACHER_NUMBER = None

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

def _xml_local_name(tag):
    return str(tag).rsplit('}', 1)[-1]

def _hwpx_element_text(element):
    pieces = []
    for node in element.iter():
        if _xml_local_name(node.tag) == 't' and node.text:
            text = ' '.join(node.text.split())
            if text:
                pieces.append(text)
    return ' '.join(pieces).strip()

def _hwpx_table_rows(root):
    tables = []
    for table in root.iter():
        if _xml_local_name(table.tag) != 'tbl':
            continue
        rows = []
        for row in table.iter():
            if _xml_local_name(row.tag) != 'tr':
                continue
            cells = [
                _hwpx_element_text(cell)
                for cell in row.iter()
                if _xml_local_name(cell.tag) == 'tc'
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables

def _schedule_entry_from_hwpx_row(cells, fallback_period):
    import re
    time_pattern = re.compile(r'(?<!\d)([01]?\d|2[0-3])\s*[:：]\s*([0-5]\d)(?!\d)')
    joined = ' | '.join(cells)
    matches = list(time_pattern.finditer(joined))
    if len(matches) < 2:
        return None

    start_hour, start_minute = map(int, matches[0].groups())
    end_hour, end_minute = map(int, matches[1].groups())
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total or end_total - start_total > 180:
        return None

    label_candidates = []
    for cell in cells:
        without_times = time_pattern.sub(' ', cell)
        without_times = re.sub(r'\b\d+\s*분\b', ' ', without_times)
        cleaned = re.sub(r'[~∼〜～\-–—:：|()\[\]]+', ' ', without_times)
        cleaned = ' '.join(cleaned.split()).strip()
        if cleaned:
            label_candidates.append(cleaned)

    label = ''
    for candidate in label_candidates:
        if re.search(r'\d+\s*교시|점심|조회|종례|청소|수업|행사|활동', candidate):
            label = candidate
            break
    if not label and label_candidates:
        label = label_candidates[0]
    if re.fullmatch(r'\d+', label):
        label += '교시'
    if not label or label in ('구분', '시간', '시정', '일정'):
        label = f'{fallback_period}교시'

    return {
        'name': label,
        'start': f'{start_hour:02d}:{start_minute:02d}',
        'end': f'{end_hour:02d}:{end_minute:02d}',
    }

def _schedule_from_hwpx_rows(rows):
    schedule = []
    seen = set()
    for cells in rows:
        entry = _schedule_entry_from_hwpx_row(cells, len(schedule) + 1)
        if not entry:
            continue
        key = (entry['name'], entry['start'], entry['end'])
        if key in seen:
            continue
        seen.add(key)
        schedule.append(entry)
    return schedule

def parse_hwpx_schedule(path):
    import zipfile
    import xml.etree.ElementTree as ET

    if not str(path).lower().endswith('.hwpx'):
        raise ValueError('HWPX 파일을 선택해 주세요.')
    if os.path.getsize(path) > 50 * 1024 * 1024:
        raise ValueError('HWPX 파일이 너무 큽니다. 50MB 이하 파일을 선택해 주세요.')

    tables = []
    paragraph_rows = []
    total_xml_size = 0
    try:
        with zipfile.ZipFile(path, 'r') as archive:
            section_names = sorted(
                name for name in archive.namelist()
                if name.startswith('Contents/section') and name.lower().endswith('.xml')
            )
            if not section_names:
                raise ValueError('HWPX 본문을 찾을 수 없습니다.')
            for name in section_names:
                info = archive.getinfo(name)
                total_xml_size += info.file_size
                if total_xml_size > 20 * 1024 * 1024:
                    raise ValueError('HWPX 본문이 너무 큽니다.')
                root = ET.fromstring(archive.read(name))
                tables.extend(_hwpx_table_rows(root))
                for paragraph in root.iter():
                    if _xml_local_name(paragraph.tag) == 'p':
                        text = _hwpx_element_text(paragraph)
                        if text:
                            paragraph_rows.append([text])
    except zipfile.BadZipFile:
        raise ValueError('올바른 HWPX 파일이 아닙니다.')
    except ET.ParseError:
        raise ValueError('HWPX 본문 XML을 읽을 수 없습니다.')

    candidates = [_schedule_from_hwpx_rows(rows) for rows in tables]
    candidates = [schedule for schedule in candidates if schedule]
    schedule = max(candidates, key=len) if candidates else _schedule_from_hwpx_rows(paragraph_rows)
    if len(schedule) < 2:
        raise ValueError('교시명과 시작·종료 시각이 있는 시정표를 찾지 못했습니다.')
    return schedule

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

def migrate_schedule(data):
    """Upgrade persisted schedules without treating the 2.1.x short timetable as special."""
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_SCHEDULE)

    migrated = copy.deepcopy(data)
    if not isinstance(migrated.get('seven_period_days'), list):
        legacy_short_days = migrated.get('six_period_days')
        if not isinstance(legacy_short_days, list):
            legacy_short_days = migrated.get('short_days')
        if not isinstance(legacy_short_days, list):
            legacy_short_days = [3, 5]
        short_days = {
            day for day in legacy_short_days
            if isinstance(day, int) and 1 <= day <= 5
        }
        migrated['seven_period_days'] = [day for day in range(1, 6) if day not in short_days]

    # In 2.1.x, `short` meant the ordinary six-period day. It must never
    # become the 2.2.x date-specific exceptional schedule.
    if not isinstance(migrated.get('special'), list):
        migrated['special'] = []
    if not isinstance(migrated.get('special_schedules'), list):
        legacy_schedule = migrated.get('special') or []
        legacy_dates = migrated.get('special_dates') or []
        migrated['special_schedules'] = []
        if legacy_schedule:
            migrated['special_schedules'].append({
                'id': 'legacy-special-schedule',
                'name': '기존 특별 시간표',
                'source_file': '',
                'schedule': copy.deepcopy(legacy_schedule),
                'dates': sorted({
                    value for value in legacy_dates
                    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
                }),
            })
    normalized_profiles = []
    claimed_dates = set()
    for index, profile in enumerate(migrated['special_schedules']):
        if not isinstance(profile, dict) or len(normalized_profiles) >= 30:
            continue
        profile_dates = profile.get('dates') if isinstance(profile.get('dates'), list) else []
        profile_schedule = profile.get('schedule') if isinstance(profile.get('schedule'), list) else []
        dates = []
        for value in profile_dates:
            if (isinstance(value, str)
                    and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
                    and value not in claimed_dates):
                dates.append(value)
                claimed_dates.add(value)
        normalized_profiles.append({
            'id': str(profile.get('id') or f'special-{index + 1}')[:100],
            'name': str(profile.get('name') or f'특별 시간표 {index + 1}')[:80],
            'source_file': str(profile.get('source_file') or '')[:255],
            'schedule': [
                copy.deepcopy(item) for item in profile_schedule
                if isinstance(item, dict)
            ],
            'dates': sorted(dates),
        })
    migrated['special_schedules'] = normalized_profiles
    if migrated.get('special_schedule_opt_in_version') != 1:
        migrated['special_schedule_enabled'] = False
        migrated['special_schedule_opt_in_version'] = 1
    return migrated

def load_schedule():
    if os.path.exists(SCHEDULE_PATH):
        try:
            with open(SCHEDULE_PATH, 'r', encoding='utf-8') as f:
                return migrate_schedule(json.load(f))
        except:
            pass
    return copy.deepcopy(DEFAULT_SCHEDULE)

def save_schedule(data):
    with open(SCHEDULE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_progress():
    if os.path.exists(PROGRESS_PATH):
        try:
            with open(PROGRESS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {'classes': {}}

def _progress_records(value):
    """Accept both the legacy single-record shape and the recent-history shape."""
    if isinstance(value, list):
        return [record for record in value if isinstance(record, dict)]
    if isinstance(value, dict) and isinstance(value.get('records'), list):
        return [record for record in value['records'] if isinstance(record, dict)]
    if isinstance(value, dict) and value:
        return [value]
    return []

def _save_progress(data):
    temp_path = PROGRESS_PATH + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, PROGRESS_PATH)

def _capture_desktop(path):
    """Capture the desktop using only OS-provided facilities."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if IS_MAC:
        result = subprocess.run(
            ['/usr/sbin/screencapture', '-x', path],
            capture_output=True, timeout=15,
        )
    else:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "Add-Type -AssemblyName System.Drawing;"
            "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
            "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
            "$g=[System.Drawing.Graphics]::FromImage($i);"
            "$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size);"
            "$i.Save($args[0],[System.Drawing.Imaging.ImageFormat]::Png);"
            "$g.Dispose();$i.Dispose()"
        )
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', script, path],
            capture_output=True, timeout=15,
        )
    if result.returncode != 0 or not os.path.exists(path):
        message = result.stderr.decode(errors='replace').strip()
        raise RuntimeError(message or '화면 캡처에 실패했습니다.')

def _is_powerpoint_running():
    if not IS_MAC:
        return False
    try:
        for application in NSWorkspace.sharedWorkspace().runningApplications():
            bundle_id = str(application.bundleIdentifier() or '')
            app_name = str(application.localizedName() or '')
            if bundle_id.lower() == 'com.microsoft.powerpoint' or app_name == 'Microsoft PowerPoint':
                return True
        return False
    except Exception:
        try:
            return subprocess.run(
                ['/usr/bin/pgrep', '-x', 'Microsoft PowerPoint'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).returncode == 0
        except Exception:
            return False

def _progress_public_record(record, include_image=False):
    result = {key: value for key, value in record.items() if key != 'image_path'}
    result['has_image'] = bool(record.get('image_path') and os.path.exists(record['image_path']))
    if include_image and result['has_image']:
        try:
            with open(record['image_path'], 'rb') as f:
                result['image_data_url'] = 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii')
        except Exception:
            result['has_image'] = False
    return result

# ─────────────────────────────────────────
# JS API
# ─────────────────────────────────────────
class Api:
    def __init__(self):
        self.settings_window = None
        self.progress_window = None
        self.progress_history_window = None
        self.lesson_end_window = None
        self.powerpoint_confirm_window = None
        self._lesson_end_payload = None
        self._lesson_end_submitting = False
        self._progress_popup_payload = None
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
                main_window.resize(320, 175)
            else:
                main_window.resize(340, 700)
        threading.Timer(0, _do).start()

    def set_lesson_dialog_open(self, opened, is_mini):
        if not is_mini:
            return True
        def _do():
            main_window.resize(360, 560 if opened else 175)
        threading.Timer(0, _do).start()
        return True

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

    def open_progress_popup(self, payload):
        if not isinstance(payload, dict):
            return False
        self._progress_popup_payload = payload
        if self.progress_window is not None and self.progress_window in webview.windows:
            encoded = json.dumps(payload, ensure_ascii=False)
            def _update():
                try:
                    self.progress_window.evaluate_js(f'renderProgress({encoded})')
                    self.progress_window.on_top = True
                except Exception:
                    pass
            threading.Timer(0, _update).start()
            return True

        self.progress_window = webview.create_window(
            title='지난 수업 진도',
            url=PROGRESS_HTML,
            width=460,
            height=580,
            min_size=(340, 280),
            resizable=True,
            on_top=True,
            js_api=self,
        )

        def on_closed():
            self.progress_window = None
        self.progress_window.events.closed += on_closed
        return True

    def get_progress_popup_data(self):
        return self._progress_popup_payload

    def close_progress_popup(self):
        if self.progress_window:
            try:
                self.progress_window.destroy()
            except Exception:
                pass
            self.progress_window = None
        return True

    def open_progress_history(self):
        if self.progress_history_window is not None:
            if self.progress_history_window in webview.windows:
                try:
                    self.progress_history_window.on_top = True
                except Exception:
                    pass
                return True
            self.progress_history_window = None

        self.progress_history_window = webview.create_window(
            title='진도 기록',
            url=PROGRESS_HISTORY_HTML,
            width=760,
            height=650,
            min_size=(560, 420),
            resizable=True,
            js_api=self,
        )

        def on_closed():
            self.progress_history_window = None
        self.progress_history_window.events.closed += on_closed
        return True

    def close_progress_history(self):
        if self.progress_history_window:
            try:
                self.progress_history_window.destroy()
            except Exception:
                pass
            self.progress_history_window = None
        return True

    def open_lesson_end_dialog(self, payload):
        if not isinstance(payload, dict):
            return False
        self._lesson_end_payload = payload
        if self.lesson_end_window is not None:
            if self.lesson_end_window in webview.windows:
                encoded = json.dumps(payload, ensure_ascii=False)
                try:
                    self.lesson_end_window.evaluate_js(f'renderLessonEnd({encoded})')
                    self.lesson_end_window.on_top = True
                except Exception:
                    pass
                return True
            self.lesson_end_window = None

        self._lesson_end_submitting = False
        self.lesson_end_window = webview.create_window(
            title='수업 종료',
            url=LESSON_END_HTML,
            width=430,
            height=340,
            min_size=(360, 300),
            resizable=True,
            on_top=True,
            js_api=self,
        )

        def on_closed():
            was_submitting = self._lesson_end_submitting
            self.lesson_end_window = None
            self._lesson_end_submitting = False
            if not was_submitting:
                threading.Timer(0, lambda: main_window.evaluate_js('cancelLessonEndDialog()')).start()
        self.lesson_end_window.events.closed += on_closed
        return True

    def get_lesson_end_dialog_data(self):
        return self._lesson_end_payload or {}

    def submit_lesson_end_dialog(self, note='', capture=True):
        payload = {
            'note': str(note or '')[:2000],
            'capture': bool(capture),
        }
        self._lesson_end_submitting = True

        def close_and_submit():
            window = self.lesson_end_window
            if window:
                try:
                    window.destroy()
                except Exception:
                    pass
            encoded = json.dumps(payload, ensure_ascii=False)
            threading.Timer(
                0.2,
                lambda: main_window.evaluate_js(f'completeLessonEndDialog({encoded})'),
            ).start()
        threading.Timer(0, close_and_submit).start()
        return True

    def close_lesson_end_dialog(self):
        if self.lesson_end_window:
            try:
                self.lesson_end_window.destroy()
            except Exception:
                pass
        return True

    def open_powerpoint_quit_dialog(self):
        if not _is_powerpoint_running():
            return False

        if self.powerpoint_confirm_window is not None:
            if self.powerpoint_confirm_window in webview.windows:
                try:
                    self.powerpoint_confirm_window.on_top = True
                except Exception:
                    pass
                return True
            self.powerpoint_confirm_window = None

        self.powerpoint_confirm_window = webview.create_window(
            title='PowerPoint 종료 확인',
            url=POWERPOINT_CONFIRM_HTML,
            width=410,
            height=230,
            min_size=(360, 210),
            resizable=False,
            on_top=True,
            js_api=self,
        )

        def on_closed():
            self.powerpoint_confirm_window = None
        self.powerpoint_confirm_window.events.closed += on_closed
        return True

    def close_powerpoint_quit_dialog(self):
        if self.powerpoint_confirm_window:
            try:
                self.powerpoint_confirm_window.destroy()
            except Exception:
                pass
            self.powerpoint_confirm_window = None
        return True

    def confirm_powerpoint_quit(self):
        self.close_powerpoint_quit_dialog()
        return self.quit_powerpoint()

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

    def get_lesson_progress(self, class_name, include_image=False):
        class_name = str(class_name or '').strip()
        if not class_name:
            return None
        with PROGRESS_LOCK:
            records = _progress_records(_load_progress().get('classes', {}).get(class_name))
            record = records[0] if records else None
            return _progress_public_record(record, bool(include_image)) if record else None

    def get_lesson_progress_history(self, class_name, include_images=True):
        class_name = str(class_name or '').strip()
        if not class_name:
            return []
        with PROGRESS_LOCK:
            records = _progress_records(_load_progress().get('classes', {}).get(class_name))[:3]
            return [_progress_public_record(record, bool(include_images)) for record in records]

    def get_all_lesson_progress(self):
        with PROGRESS_LOCK:
            classes = _load_progress().get('classes', {})
            result = []
            for class_name, value in classes.items():
                records = _progress_records(value)[:3]
                if not records:
                    continue
                latest = records[0]
                result.append({
                    'class_name': str(class_name),
                    'count': len(records),
                    'subject': latest.get('subject', ''),
                    'note': latest.get('note', ''),
                    'saved_at': latest.get('saved_at', ''),
                    'saved_at_label': latest.get('saved_at_label', ''),
                    'has_image': bool(latest.get('image_path') and os.path.exists(latest['image_path'])),
                })
            result.sort(key=lambda item: item.get('saved_at', ''), reverse=True)
            return result

    def update_lesson_progress_note(self, class_name, lesson_id, note=''):
        class_name = str(class_name or '').strip()
        lesson_id = str(lesson_id or '').strip()[:100]
        note = str(note or '').strip()[:2000]
        if not class_name or not lesson_id:
            return {'ok': False, 'error': '수정할 진도 기록을 찾을 수 없습니다.'}

        with PROGRESS_LOCK:
            data = _load_progress()
            classes = data.setdefault('classes', {})
            records = _progress_records(classes.get(class_name))
            record = next((item for item in records if item.get('lesson_id') == lesson_id), None)
            if record is None:
                return {'ok': False, 'error': '수정할 진도 기록을 찾을 수 없습니다.'}
            record['note'] = note
            classes[class_name] = records[:3]
            _save_progress(data)
            return {'ok': True, 'record': _progress_public_record(record)}

    def save_lesson_progress(self, class_name, subject='', note='', capture=False,
                             lesson_id='', automatic=False):
        class_name = str(class_name or '').strip()
        subject = str(subject or '').strip()
        note = str(note or '').strip()[:2000]
        lesson_id = str(lesson_id or '').strip()[:100]
        if not class_name:
            return {'ok': False, 'error': '반 정보가 없는 수업은 진도를 저장할 수 없습니다.'}

        with PROGRESS_LOCK:
            data = _load_progress()
            classes = data.setdefault('classes', {})
            history = _progress_records(classes.get(class_name))
            previous = history[0] if history else {}
            if automatic and lesson_id and previous.get('lesson_id') == lesson_id:
                return {'ok': True, 'duplicate': True, 'record': _progress_public_record(previous)}

            now = datetime.datetime.now().astimezone()
            record = {
                'class_name': class_name,
                'subject': subject,
                'note': note,
                'saved_at': now.isoformat(timespec='seconds'),
                'saved_at_label': now.strftime('%Y.%m.%d %H:%M'),
                'lesson_id': lesson_id,
                'automatic': bool(automatic),
            }
            capture_error = None
            if capture:
                digest = hashlib.sha256(class_name.encode('utf-8')).hexdigest()[:12]
                filename = now.strftime('%Y%m%d_%H%M%S_') + digest + '.png'
                image_path = os.path.join(PROGRESS_IMAGE_DIR, filename)
                try:
                    _capture_desktop(image_path)
                    record['image_path'] = image_path
                except Exception as e:
                    capture_error = str(e)

            same_lesson = bool(lesson_id) and previous.get('lesson_id') == lesson_id
            discarded = [previous] if same_lesson and previous else []
            updated_history = [record] + (history[1:] if same_lesson else history)
            discarded.extend(updated_history[3:])
            updated_history = updated_history[:3]
            classes[class_name] = updated_history
            _save_progress(data)
            retained_images = {item.get('image_path') for item in updated_history if item.get('image_path')}
            for old_record in discarded:
                old_image = old_record.get('image_path')
                if old_image and old_image not in retained_images and os.path.exists(old_image):
                    try:
                        os.remove(old_image)
                    except OSError:
                        pass
            # The completion popup needs the exact screenshot that was just saved.
            result = {'ok': True, 'record': _progress_public_record(record, bool(capture))}
            if capture_error:
                result['capture_error'] = capture_error
            return result

    def quit_powerpoint(self):
        """Ask PowerPoint to quit normally so it can prompt for unsaved files."""
        if not IS_MAC:
            return {'ok': False, 'unsupported': True}
        script = (
            'if application "Microsoft PowerPoint" is running then\n'
            'tell application "Microsoft PowerPoint" to quit\n'
            'end if'
        )
        try:
            subprocess.Popen(
                ['osascript', '-e', script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def capture_lesson_preview(self):
        """Capture a disposable image for the settings preview without saving a record."""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                image_path = os.path.join(temp_dir, 'preview.png')
                _capture_desktop(image_path)
                with open(image_path, 'rb') as f:
                    encoded = base64.b64encode(f.read()).decode('ascii')
            return {'ok': True, 'image_data_url': 'data:image/png;base64,' + encoded}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

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

    def import_hwpx_schedule(self):
        if not self.settings_window:
            return {'ok': False, 'error': '설정 창을 먼저 열어 주세요.'}
        try:
            result = self.settings_window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=('HWPX files (*.hwpx)', 'All files (*.*)')
            )
            if not result:
                return {'ok': False, 'cancelled': True}
            path = result[0] if isinstance(result, (list, tuple)) else result
            schedule = parse_hwpx_schedule(path)
            return {
                'ok': True,
                'filename': os.path.basename(path),
                'schedule': schedule,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}

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

if not IS_MAC:
    _patch_edgechromium_transparency()

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
