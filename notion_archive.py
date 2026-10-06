"""Archive each week's merged personal timetable as a Notion page."""
import datetime as dt
import json
import re
import ssl
import urllib.error
import urllib.request

from admin_credentials import AdminCredentials
from personal_timetable import comci_entry, day_schedule, merge_comci_personal

API_URL = 'https://api.notion.com/v1/pages'
NOTION_VERSION = '2022-06-28'
SERVICE = 'com.whattime.notion-archive'
ACCOUNT = 'integration-token'
DAY_NAMES = '월화수목금'
CHANGED_MARK = ' 🔄'


def credentials(vault=None):
    return AdminCredentials(vault, service=SERVICE, account=ACCOUNT)


def parse_page_id(value):
    tail = re.split(r'[?#]', str(value or '').strip())[0].rstrip('/').rsplit('/', 1)[-1].replace('-', '')
    match = re.search(r'[0-9a-fA-F]{32}$', tail)
    if not match:
        raise ValueError('노션 보관 페이지 링크를 확인하세요.')
    return match[0].lower()


def period_label(name):
    return re.sub(r'\s*\(.*?\)\s*$', '', name or '').strip()


def week_lessons(data, result):
    """Lessons per weekday as the app shows them, plus Comci's changed-lesson flag."""
    imported = result.get('personal')
    personal = merge_comci_personal(data, imported)
    joam_rule = bool(data.get('comci_joam_first_grade_fifth_period'))
    week = {}
    for day in range(1, 6):
        lessons = []
        for item, entry in zip(day_schedule(data, day), personal[str(day)]):
            if not entry.get('name'):
                continue
            changed = (entry.get('source') == 'comci' and
                       bool(comci_entry(item, imported[str(day)], joam_rule).get('changed')))
            lessons.append({'row': item.get('name', ''), 'start': item.get('start', ''), 'end': item.get('end', ''),
                            'name': entry['name'], 'room': entry.get('room', ''), 'changed': changed})
        week[day] = lessons
    return week


def _text(content):
    return [{'type': 'text', 'text': {'content': content}}] if content else []


def _block(kind, content):
    return {'object': 'block', 'type': kind, kind: {'rich_text': _text(content)}}


def _time_range(row):
    return f"{row['start']}–{row['end']}" if row.get('start') and row.get('end') else ''


def _date(day):
    return f'{day.month}/{day.day}'


def build_page(data, result, monday, parent_id):
    week = week_lessons(data, result)
    dates = [monday + dt.timedelta(days=offset) for offset in range(5)]
    by_row = {day: {lesson['row']: lesson for lesson in lessons} for day, lessons in week.items()}

    table = [[_text('교시')] + [_text(f'{DAY_NAMES[i]} {_date(dates[i])}') for i in range(5)]]
    for row in data.get('full') or []:
        if not any(row.get('name') in by_row[day] for day in week):
            continue
        cells = [_text(' '.join(filter(None, [period_label(row.get('name')), _time_range(row)])))]
        for day in range(1, 6):
            lesson = by_row[day].get(row.get('name'))
            cells.append(_text(' '.join(filter(None, [lesson['name'], lesson['room']])) +
                               (CHANGED_MARK if lesson['changed'] else '')) if lesson else [])
        table.append(cells)

    school = data.get('comci_school_name') or ('' if result.get('school_name_hidden') else result.get('school_name', ''))
    source = ' · '.join(filter(None, [school, f"컴시간 {result['updated_at']} 기준" if result.get('updated_at') else '',
                                      'WhatTime에서 자동 보관']))
    children = [_block('paragraph', source), _block('heading_2', '한눈에 보기')]
    if len(table) > 1:
        children.append({'object': 'block', 'type': 'table', 'table': {
            'table_width': 6, 'has_column_header': True, 'has_row_header': True,
            'children': [{'object': 'block', 'type': 'table_row', 'table_row': {'cells': cells}} for cells in table]}})
    else:
        children.append(_block('paragraph', '이번 주 수업 없음'))
    if any(lesson['changed'] for lessons in week.values() for lesson in lessons):
        children.append(_block('paragraph', CHANGED_MARK.strip() + ' = 컴시간에 변경된 수업으로 표시된 칸'))

    children.append(_block('heading_2', '요일별'))
    for day in range(1, 6):
        lessons = week[day]
        periods = sum(1 for lesson in lessons if re.match(r'^\s*\d+교시', lesson['row']))
        heading = f'{DAY_NAMES[day - 1]} {_date(dates[day - 1])}' + (f' · 수업 {periods}시간' if periods else '')
        children.append(_block('heading_3', heading))
        if not lessons:
            children.append(_block('paragraph', '수업 없음'))
        for lesson in lessons:
            line = ' · '.join(filter(None, [
                ' '.join(filter(None, [period_label(lesson['row']), _time_range(lesson)])), lesson['name'], lesson['room']]))
            children.append(_block('bulleted_list_item', line + (CHANGED_MARK if lesson['changed'] else '')))

    title = f'수업 시간표 {monday:%Y.%m.%d}~{dates[4]:%m.%d}'
    return {'parent': {'type': 'page_id', 'page_id': parent_id}, 'icon': {'type': 'emoji', 'emoji': '📅'},
            'properties': {'title': {'title': _text(title)}}, 'children': children}


def notion_request(url, token, payload, method='POST'):
    headers = {'Authorization': 'Bearer ' + token, 'Notion-Version': NOTION_VERSION,
               'Content-Type': 'application/json', 'User-Agent': 'WhatTime-Notion'}
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    req = urllib.request.Request(url, headers=headers, data=json.dumps(payload).encode('utf-8'), method=method)
    with urllib.request.urlopen(req, timeout=15, context=context) as response:
        return json.loads(response.read())


def archive_week(data, result, token, now=None, send=notion_request):
    """Create this week's page; a repeat import in the same week replaces that week's page."""
    if not token:
        raise ValueError('노션 통합 토큰을 먼저 저장하세요.')
    parent_id = parse_page_id(data.get('notion_archive_page'))
    now = now or dt.datetime.now().astimezone()
    monday = now.date() - dt.timedelta(days=now.weekday())
    page = send(API_URL, token, build_page(data, result, monday, parent_id))
    previous = data.get('notion_last_archive') or {}
    if previous.get('week') == monday.isoformat() and previous.get('page_id'):
        try:
            send(f"{API_URL}/{previous['page_id']}", token, {'archived': True}, 'PATCH')
        except (OSError, ValueError):
            pass  # The teacher may already have deleted or moved the earlier page.
    return {'week': monday.isoformat(), 'page_id': page['id'], 'url': page.get('url', ''),
            'at': now.isoformat(timespec='seconds')}


def error_message(error):
    if isinstance(error, urllib.error.HTTPError):
        return {400: '노션이 요청을 거절했어요. 보관 페이지 링크를 확인하세요.',
                401: '노션 통합 토큰을 확인하세요.',
                403: '노션 통합에 페이지 권한이 없어요.',
                404: '노션 보관 페이지를 찾지 못했어요. 페이지에 통합을 연결했는지 확인하세요.',
                429: '노션 요청이 많아요. 잠시 후 다시 불러오세요.'}.get(error.code, f'노션 응답 오류 ({error.code})')
    if isinstance(error, ValueError):
        return str(error)
    return '노션에 보관하지 못했어요. 인터넷 연결과 토큰 저장소를 확인하세요.'
