"""Lesson reminders using OS idle duration only; no keystrokes or mouse positions are collected."""
import datetime as dt
import math
import re
import sys
import threading
from personal_timetable import day_schedule
from lesson_mapping import special_scope, resolve_personal


def input_idle_seconds():
    if sys.platform == 'darwin':
        import Quartz
        seconds = Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGAnyInputEventType)
    elif sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        get_last_input = ctypes.windll.user32.GetLastInputInfo
        get_last_input.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        get_last_input.restype = wintypes.BOOL
        if not get_last_input(ctypes.byref(info)):
            raise OSError('최근 입력 시간을 확인할 수 없어요.')
        get_tick = ctypes.windll.kernel32.GetTickCount
        get_tick.restype = wintypes.DWORD
        seconds = ((get_tick() - info.dwTime) & 0xffffffff) / 1000.0
    else:
        raise OSError('이 운영체제에서는 입력 감지를 지원하지 않아요.')
    if not math.isfinite(seconds) or seconds < 0:
        raise OSError('최근 입력 시간을 확인할 수 없어요.')
    return float(seconds)


def schedule_for_date(data, school, date):
    key = date.isoformat()
    if data.get('special_schedule_enabled', True):
        profiles = data.get('special_schedules') or []
        profile = next((p for p in profiles if key in p.get('dates', [])), None)
        if profile and profile.get('schedule'):
            return profile['schedule'], False
        if not profiles and key in (data.get('special_dates') or []) and data.get('special'):
            return data['special'], False
    published = next((e for e in (school or {}).get('events', []) if e['date'] == key), None)
    if published:
        return published['periods'], True
    day = (date.weekday() + 1) % 7
    if day in data.get('rest_days', [0, 6]):
        return (data.get('rest_schedules') or {}).get(str(day), []), False
    return day_schedule(data, day), False


def personal_entry(data, item, index, day, subscribed):
    if subscribed:
        number = re.match(r'^\s*(\d+)교시', item.get('name', ''))
        ordinary = day_schedule(data, day)
        index = -1
        for i, row in enumerate(ordinary):
            row_number = re.match(r'^\s*(\d+)교시', row.get('name', ''))
            if (number and row_number and number[1] == row_number[1]) or (not number and row.get('name') == item.get('name')):
                index = i
                break
    entries = (data.get('personal') or {}).get(str(day), [])
    return entries[index] if 0 <= index < len(entries) else {}


def current_lesson(data, school, now):
    """Resolve actual scheduled classes, independent of progress saving and UI previews."""
    offset = float(data.get('time_offset_seconds') or 0)
    adjusted = now + dt.timedelta(seconds=offset)
    for date in [adjusted.date(), adjusted.date() - dt.timedelta(days=1)]:
        schedule, subscribed = schedule_for_date(data, school, date)
        day = (date.weekday() + 1) % 7
        context = special_scope(data, school, date)
        for index, item in enumerate(schedule):
            if item.get('no_countdown'):
                continue
            entry = resolve_personal(data, date, context[0], item) if context else personal_entry(data, item, index, day, subscribed)
            room = str(entry.get('room') or '').strip()
            name = str(item.get('name') or '')
            is_period = bool(re.match(r'^\s*\d+교시', name))
            is_first_grade_lunch = (data.get('comci_joam_first_grade_fifth_period') and
                                   '점심' in name and '1학년 5교시' in name and room.startswith('1-'))
            if not room or not (context or is_period or is_first_grade_lunch):
                continue
            try:
                start = dt.datetime.combine(date, dt.time.fromisoformat(item['start']))
                end = dt.datetime.combine(date, dt.time.fromisoformat(item['end']))
                if end <= start:
                    end += dt.timedelta(days=1)
            except (ValueError, KeyError, TypeError):
                continue
            # The app's clock calibration affects when the reminder fires too.
            if start <= adjusted.replace(tzinfo=None) < end:
                start_ts = (start - dt.timedelta(seconds=offset)).timestamp()
                end_ts = (end - dt.timedelta(seconds=offset)).timestamp()
                return {'id': f'{date.isoformat()}:{item["start"]}:{room}',
                        'class_name': room, 'subject': str(entry.get('name') or '').strip(),
                        'period': name, 'start': item['start'], 'end': item['end'],
                        'start_ts': start_ts, 'end_ts': end_ts}
    return None


class ReminderEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.records = {}

    def tick(self, lesson, now, idle_seconds=None):
        if not lesson:
            return None
        key = lesson['id']
        with self.lock:
            if key not in self.records:
                elapsed = now - lesson['start_ts']
                if elapsed < 0:
                    return None
                self.records[key] = {'initial': False, 'urgent': False, 'muted': elapsed > 30,
                                     'ignore_input_before': now}
                if len(self.records) > 128:
                    del self.records[next(iter(self.records))]
            record = self.records[key]
            if record['muted'] or now >= lesson['end_ts']:
                return None
            if not record['initial']:
                record['initial'] = True
                return {**lesson, 'level': 'start', 'elapsed_seconds': max(0, int(now - lesson['start_ts']))}
            if record['urgent'] or idle_seconds is None or not math.isfinite(idle_seconds) or idle_seconds < 0:
                return None
            last_input = now - idle_seconds
            if (now >= lesson['start_ts'] + 20 and last_input >= lesson['start_ts'] + 20
                    and last_input > record['ignore_input_before'] and idle_seconds <= 5):
                record['urgent'] = True
                return {**lesson, 'level': 'urgent', 'elapsed_seconds': int(now - lesson['start_ts'])}
        return None

    def is_muted(self, lesson_id):
        with self.lock:
            return bool(self.records.get(lesson_id, {}).get('muted'))

    def dismiss(self, lesson_id, now, mute=False):
        with self.lock:
            record = self.records.get(lesson_id)
            if record:
                record['muted'] = record['muted'] or mute
                # Closing the first popup alone is not evidence of continued work.
                record['ignore_input_before'] = now + 1
