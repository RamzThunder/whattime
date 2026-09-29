"""Special-schedule lesson links. Keep semantics aligned with lesson_mapping.js."""
import json
import re
from personal_timetable import day_schedule


def inferred(item):
    name = str(item.get('name') or '').strip()
    if re.search(r'점심.*1학년\s*5교시', name):
        return {'lesson_period': 5, 'grades': [1]}
    match = re.match(r'^(?:([1-3])학년\s*)?(?:제\s*)?(\d+)\s*교시', name)
    grades = [int(match[1])] if match and match[1] else [1, 2, 3]
    lunch = re.search(r'\(([1-3])학년\s*(?:급식|점심)\)', name)
    if lunch:
        grades = [n for n in grades if n != int(lunch[1])]
    return {'lesson_period': int(match[2]) if match else 0, 'grades': grades}


def special_scope(data, school, date):
    key = date.isoformat()
    if data.get('special_schedule_enabled', True):
        profiles = data.get('special_schedules') or []
        for profile in profiles:
            if key in profile.get('dates', []) and profile.get('schedule'):
                return 'local:' + str(profile.get('id') or ''), profile['schedule']
        if not profiles and key in data.get('special_dates', []) and data.get('special'):
            return 'local:legacy', data['special']
    for event in (school or {}).get('events', []):
        if event['date'] == key:
            return 'school:' + str(school.get('id') or ''), event['periods']
    return None


def resolve_personal(data, date, scope, item):
    key = item.get('id') or json.dumps([item.get(k) or '' for k in ('name', 'start', 'end')], ensure_ascii=False, separators=(',', ':'))
    own = (data.get('special_personal_overrides') or {}).get(date.isoformat(), {}).get(scope, {}).get(key, {})
    if own.get('mode') == 'none':
        return {}
    if own.get('mode') == 'custom':
        return {'name': own.get('name', ''), 'room': own.get('room', '')}
    merged = {**item, **own}
    mapping = {**inferred(merged), **{k: merged[k] for k in ('lesson_period', 'grades') if k in merged}}
    day = (date.weekday() + 1) % 7
    base = day_schedule(data, day)
    entries = (data.get('personal') or {}).get(str(day), [])
    index = -1
    if mapping['lesson_period']:
        if mapping['lesson_period'] == 5 and data.get('comci_joam_first_grade_fifth_period'):
            index = next((i for i, row in enumerate(base) if '점심' in row.get('name', '') and '1학년 5교시' in row.get('name', '')
                          and i < len(entries) and str(entries[i].get('room', '')).startswith('1-')), -1)
        if index < 0:
            index = next((i for i, row in enumerate(base) if inferred(row)['lesson_period'] == mapping['lesson_period']), -1)
    elif 'lesson_period' not in merged:
        index = next((i for i, row in enumerate(base) if row.get('name') == item.get('name')), -1)
    if not 0 <= index < len(entries):
        return {}
    entry = entries[index]
    grade = re.match(r'^([1-3])(?:\s*-|학년)', str(entry.get('room') or '').strip())
    if len(mapping['grades']) != 3 and (not grade or int(grade[1]) not in mapping['grades']):
        return {}
    return entry
