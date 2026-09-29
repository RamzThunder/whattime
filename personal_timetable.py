"""Merge Comci lessons without replacing teacher-authored personal entries."""
import copy
import datetime as dt
import re


def has_personal_override(entry):
    if not isinstance(entry, dict):
        return False
    if entry.get('source') == 'manual':
        return True
    if entry.get('source') == 'comci':
        return False
    # Older versions did not record provenance. Preserve populated legacy cells.
    return bool(entry.get('name') or entry.get('room'))


def day_schedule(data, day):
    full = data.get('full') or []
    if day in data.get('seven_period_days', [1, 2, 4]):
        return full
    return [row for row in full if not re.match(r'^\s*7교시', row.get('name', ''))]


def comci_entry(item, imported, joam_rule=False):
    name = item.get('name', '')
    fifth = imported[4] if len(imported) > 4 else {}
    first_grade = str(fifth.get('room', '')).strip().startswith('1-')
    if joam_rule and '점심' in name and '1학년 5교시' in name:
        return fifth if first_grade else {}
    if joam_rule and '5교시' in name and '1학년 점심' in name:
        return {} if first_grade else fifth
    match = re.match(r'^\s*(\d+)교시', name)
    index = int(match[1]) - 1 if match else -1
    return imported[index] if 0 <= index < len(imported) else {}


def merge_comci_personal(data, imported):
    if not isinstance(imported, dict) or any(not isinstance(imported.get(str(day)), list) for day in range(1, 6)):
        raise ValueError('컴시간의 요일별 시간표가 올바르지 않아요.')
    for rows in imported.values():
        if not isinstance(rows, list) or any(not isinstance(row, dict) or
                not isinstance(row.get('name', ''), str) or not isinstance(row.get('room', ''), str) for row in rows):
            raise ValueError('컴시간의 교시 정보가 올바르지 않아요.')
    personal = copy.deepcopy(data.get('personal') or {})
    for day in range(1, 6):
        key = str(day)
        existing = personal.setdefault(key, [])
        for index, item in enumerate(day_schedule(data, day)):
            while len(existing) <= index:
                existing.append({'name': '', 'room': ''})
            if has_personal_override(existing[index]):
                existing[index]['source'] = 'manual'
                continue
            entry = comci_entry(item, imported[key], bool(data.get('comci_joam_first_grade_fifth_period')))
            existing[index] = {'name': entry.get('name', ''), 'room': entry.get('room', ''), 'source': 'comci'}
    return personal


def comci_target(data):
    try:
        school = int(data.get('comci_school_code') or 0)
        teacher = int(data.get('comci_teacher_number') or 0)
    except (TypeError, ValueError):
        return None
    return (school, teacher) if school > 0 and teacher > 0 else None


def comci_weekly_due(data, today=None):
    today = today or dt.date.today()
    target = comci_target(data)
    if today.weekday() != 0 or not target or data.get('comci_weekly_auto_enabled') is False:
        return False
    last = data.get('comci_last_sync') or {}
    return not (last.get('week') == today.isoformat() and last.get('school_code') == target[0]
                and last.get('teacher_number') == target[1])


def apply_comci_result(data, result, now=None):
    """Return a new settings object; only import-owned cells and sync metadata change."""
    now = now or dt.datetime.now().astimezone()
    merged = copy.deepcopy(data)
    merged['personal'] = merge_comci_personal(data, result.get('personal'))
    target = comci_target(data)
    if not target:
        raise ValueError('학교코드와 교사 번호를 먼저 설정하세요.')
    merged['comci_last_sync'] = {
        'week': (now.date() - dt.timedelta(days=now.weekday())).isoformat(),
        'at': now.isoformat(timespec='seconds'),
        'school_code': target[0], 'teacher_number': target[1],
        'teacher_name': result.get('teacher_name', ''), 'updated_at': result.get('updated_at', ''),
    }
    merged['comci_sync_error'] = ''
    return merged
