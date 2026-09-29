"""Public GitHub schedule feed, validation, and offline subscription storage."""
import base64
import copy
import datetime as dt
import json
import os
import re
import secrets
import ssl
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SOURCE = {'repository': 'RamzThunder/whattime-releases', 'branch': 'main', 'path': 'schedules.json'}
MAX_BYTES = 2_000_000


def source_config(value):
    value = value or DEFAULT_SOURCE
    repo = str(value.get('repository', '')).strip()
    branch = str(value.get('branch', '')).strip()
    path = str(value.get('path', '')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('저장소는 소유자/저장소 형식으로 입력하세요.')
    if not branch or len(branch) > 200 or not path.endswith('.json'):
        raise ValueError('브랜치와 .json 파일 경로를 확인하세요.')
    if any(part in ('', '.', '..') for part in path.split('/')):
        raise ValueError('올바른 파일 경로를 입력하세요.')
    return {'repository': repo, 'branch': branch, 'path': path}


def clean_text(value, label, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label}: 1~{limit}자의 텍스트가 필요해요.')
    if any(ord(c) < 32 for c in value):
        raise ValueError(f'{label}: 줄바꿈이나 제어 문자는 사용할 수 없어요.')
    return value.strip()


def validate_feed(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('지원하지 않는 시정 파일 형식이에요.')
    schools = value.get('schools')
    if not isinstance(schools, list) or len(schools) > 1000:
        raise ValueError('학교 목록을 확인하세요.')
    result, school_ids = [], set()
    for school in schools:
        if not isinstance(school, dict):
            raise ValueError('학교 데이터 형식이 잘못되었어요.')
        school_id = clean_text(school.get('id'), '학교 ID')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', school_id) or school_id in school_ids:
            raise ValueError('학교 ID는 중복 없는 영문·숫자·밑줄·하이픈이어야 해요.')
        school_ids.add(school_id)
        name = clean_text(school.get('name'), '학교 이름')
        events = school.get('events')
        if not isinstance(events, list) or len(events) > 1000:
            raise ValueError('학교별 특별시정 목록을 확인하세요.')
        dates, entries = set(), []
        for event in events:
            if not isinstance(event, dict):
                raise ValueError('특별시정 형식이 잘못되었어요.')
            date = event.get('date')
            try:
                if not isinstance(date, str) or dt.date.fromisoformat(date).isoformat() != date:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError('적용 날짜는 YYYY-MM-DD 형식이어야 해요.') from None
            if date in dates:
                raise ValueError(f'{name}: {date} 시정이 중복돼요.')
            dates.add(date)
            title = clean_text(event.get('title'), '시정 제목')
            periods = event.get('periods')
            if not isinstance(periods, list) or not 1 <= len(periods) <= 100:
                raise ValueError('시정에는 1~100개의 교시가 필요해요. 취소하려면 날짜를 삭제하세요.')
            rows, previous_end, row_ids = [], '', set()
            for period in periods:
                if not isinstance(period, dict):
                    raise ValueError('교시 형식이 잘못되었어요.')
                start, end = period.get('start'), period.get('end')
                if not all(isinstance(t, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in (start, end)):
                    raise ValueError('시각은 HH:MM 형식이어야 해요.')
                if start >= end or start < previous_end:
                    raise ValueError('교시는 같은 날 안에서 시작·종료 순서대로, 겹치지 않게 입력하세요.')
                previous_end = end
                if not isinstance(period.get('no_countdown', False), bool):
                    raise ValueError('카운트다운 제외 값은 true/false여야 해요.')
                rows.append({'name': clean_text(period.get('name'), '교시 이름'), 'start': start, 'end': end,
                             'no_countdown': period.get('no_countdown', False)})
                if 'id' in period:
                    row_id = clean_text(period['id'], '교시 ID')
                    if row_id in row_ids:
                        raise ValueError('교시 ID가 중복돼요.')
                    row_ids.add(row_id)
                    rows[-1]['id'] = row_id
                if 'lesson_period' in period:
                    number = period['lesson_period']
                    if type(number) is not int or not 0 <= number <= 12:
                        raise ValueError('연결 교시는 없음 또는 1~12교시로 선택하세요.')
                    rows[-1]['lesson_period'] = number
                if 'grades' in period:
                    grades = period['grades']
                    if (not isinstance(grades, list) or not grades or
                            any(type(g) is not int or g not in (1, 2, 3) for g in grades) or len(set(grades)) != len(grades)):
                        raise ValueError('적용 학년은 1·2·3학년 중 하나 이상 선택하세요.')
                    rows[-1]['grades'] = sorted(grades)

            entry = {'date': date, 'title': title, 'periods': rows}
            if 'preserve_first_row' in event:
                if not isinstance(event['preserve_first_row'], bool):
                    raise ValueError('첫 행 유지 값은 true/false여야 해요.')
                if event['preserve_first_row']:
                    entry['preserve_first_row'] = True
            entries.append(entry)
        result.append({'id': school_id, 'name': name, 'events': sorted(entries, key=lambda e: e['date'])})
    return {'version': 1, 'schools': result}


def request_json(url, token='', method='GET', payload=None):
    headers = {'User-Agent': 'WhatTime-Schedules', 'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    if body is not None:
        headers['Content-Type'] = 'application/json'
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    req = urllib.request.Request(url, headers=headers, data=body, method=method)
    with urllib.request.urlopen(req, timeout=15, context=context) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('시정 파일이 너무 커요.')
    return json.loads(raw)


def raw_url(source):
    s = source_config(source)
    return 'https://raw.githubusercontent.com/{}/{}/{}'.format(
        s['repository'], urllib.parse.quote(s['branch'], safe=''), urllib.parse.quote(s['path'], safe='/'))


def contents_url(source):
    s = source_config(source)
    return f"https://api.github.com/repos/{s['repository']}/contents/{urllib.parse.quote(s['path'], safe='/')}"


def network_message(error):
    if isinstance(error, urllib.error.HTTPError):
        return {401: 'GitHub 인증을 확인하세요.', 403: 'GitHub 접근 권한 또는 요청 한도를 확인하세요.',
                404: '저장소·브랜치·시정 파일을 찾지 못했어요. 아직 게시 전일 수 있어요.',
                409: '다른 변경이 먼저 게시됐어요. 다시 불러온 뒤 수정하세요.',
                422: 'GitHub가 게시를 거절했어요. 브랜치와 파일 상태를 확인하세요.'}.get(error.code, f'GitHub 응답 오류 ({error.code})')
    if isinstance(error, ValueError):
        return str(error)
    return '시정 정보를 읽거나 저장하지 못했어요. 인터넷 연결과 저장 공간을 확인하세요.'


def atomic_json(path, value):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.schedule-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class SubscriptionStore:
    def __init__(self, path, fixed_source=None):
        self.fixed_source = source_config(fixed_source) if fixed_source is not None else None
        self.path = path
        self.lock = threading.RLock()
        self.sync_lock = threading.Lock()
        self.pending = None
        self.state = {'source': dict(self.fixed_source or DEFAULT_SOURCE), 'school_id': '', 'feed': {'version': 1, 'schools': []},
                      'last_checked': '', 'last_success': '', 'error': ''}
        try:
            with open(path, encoding='utf-8') as stream:
                saved = json.load(stream)
            saved['source'] = source_config(saved['source'])
            if self.fixed_source and saved['source'] != self.fixed_source:
                raise ValueError('구독 원본이 바뀌어 이전 캐시는 사용하지 않습니다.')
            saved['feed'] = validate_feed(saved['feed'])
            self.state.update(saved)
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def select(self, school_id):
        with self.lock:
            if school_id and not any(s['id'] == school_id for s in self.state['feed']['schools']):
                raise ValueError('학교 목록에서 학교를 선택하세요.')
            state = copy.deepcopy(self.state)
            state['school_id'] = school_id
            atomic_json(self.path, state)
            self.state = state
            self.pending = None
        return self.snapshot()

    def check(self, source=None, today=None):
        """Fetch a candidate without changing the schedule the user has accepted."""
        with self.sync_lock:
            current = self.snapshot()
            selected_source = source_config(self.fixed_source or source or current['source'])
            checked = dt.datetime.now().astimezone().isoformat(timespec='seconds')
            today_key = (today or dt.date.today()).isoformat()
            try:
                feed = validate_feed(request_json(raw_url(selected_source)))
                with self.lock:
                    if (self.state['source'], self.state['school_id']) != (current['source'], current['school_id']):
                        raise ValueError('구독 학교가 바뀌었어요. 다시 확인하세요.')
                    old_school = next((s for s in current['feed']['schools'] if s['id'] == current['school_id']), None)
                    new_school = next((s for s in feed['schools'] if s['id'] == current['school_id']), None)
                    old_events = {e['date']: e for e in (old_school or {}).get('events', []) if e['date'] >= today_key}
                    new_events = {e['date']: e for e in (new_school or {}).get('events', []) if e['date'] >= today_key}
                    changes = []
                    for date in sorted(old_events.keys() | new_events.keys()):
                        if old_events.get(date) == new_events.get(date):
                            continue
                        kind = '추가' if date not in old_events else '취소' if date not in new_events else '수정'
                        title = (new_events.get(date) or old_events[date])['title']
                        changes.append(f'{date} · {title} ({kind})')
                    switching = selected_source != current['source']
                    if switching and current['school_id']:
                        changes = ['구독 주소를 변경하고 학교를 다시 선택합니다.']
                    proposal_id = secrets.token_hex(16)
                    self.pending = {'id': proposal_id, 'source': selected_source, 'feed': feed,
                                    'previous_source': current['source'], 'school_id': current['school_id'],
                                    'checked': checked}
                    self.state.update(last_checked=checked, error='')
                    return {'ok': True, 'proposal_id': proposal_id,
                            'requires_confirmation': bool(changes and current['school_id']),
                            'school_name': (new_school or old_school or {}).get('name', ''),
                            'changes': changes, 'state': self.snapshot()}
            except Exception as error:
                with self.lock:
                    self.pending = None
                    self.state.update(last_checked=checked, error=network_message(error))
                return {'ok': False, 'error': network_message(error), 'state': self.snapshot()}

    def accept(self, proposal_id):
        with self.lock:
            candidate = self.pending
            if not candidate or candidate['id'] != proposal_id:
                raise ValueError('확인할 시정이 바뀌었어요. 다시 확인하세요.')
            if (self.state['source'], self.state['school_id']) != (candidate['previous_source'], candidate['school_id']):
                raise ValueError('구독 학교가 바뀌었어요. 다시 확인하세요.')
            state = copy.deepcopy(self.state)
            if candidate['source'] != state['source']:
                state['school_id'] = ''
            state.update(source=candidate['source'], feed=candidate['feed'],
                         last_checked=candidate['checked'], last_success=candidate['checked'], error='')
            atomic_json(self.path, state)
            self.state = state
            self.pending = None
            return self.snapshot()

    def decline(self, proposal_id):
        with self.lock:
            if self.pending and self.pending['id'] == proposal_id:
                self.pending = None
            return self.snapshot()

    def active_school(self):
        state = self.snapshot()
        return next((s for s in state['feed']['schools'] if s['id'] == state['school_id']), None)


class GitHubPublisher:
    def __init__(self):
        self.source = None
        self.sha = None
        self.lock = threading.Lock()

    def load(self, source, token):
        with self.lock:
            self.source, self.sha = None, None
            source = source_config(source)
            repo = request_json(f"https://api.github.com/repos/{source['repository']}", token)
            if repo.get('private', True):
                raise ValueError('사용자가 인증 없이 구독할 수 있는 공개 저장소를 선택하세요.')
            # Confirm branch exists so a missing repository/branch cannot be mistaken for a new file.
            request_json(f"https://api.github.com/repos/{source['repository']}/branches/{urllib.parse.quote(source['branch'], safe='')}", token)
            try:
                item = request_json(contents_url(source) + '?ref=' + urllib.parse.quote(source['branch'], safe=''), token)
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                self.source = source
                return {'version': 1, 'schools': []}
            if item.get('encoding') != 'base64' or not item.get('sha'):
                raise ValueError('게시 파일을 읽지 못했어요.')
            feed = validate_feed(json.loads(base64.b64decode(item['content'])))
            self.source, self.sha = source, item['sha']
            return feed

    def publish(self, source, token, feed):
        with self.lock:
            source = source_config(source)
            if self.source != source:
                raise ValueError('먼저 이 저장소의 게시 내용을 불러오세요.')
            if not token.strip():
                raise ValueError('게시하려면 GitHub 토큰이 필요해요.')
            feed = validate_feed(feed)
            raw = json.dumps(feed, ensure_ascii=False, indent=2).encode('utf-8')
            if len(raw) > 500_000:
                raise ValueError('게시 파일은 500KB 이하로 유지하세요.')
            payload = {'message': 'Update school special schedules', 'branch': source['branch'],
                       'content': base64.b64encode(raw).decode('ascii')}
            if self.sha:
                payload['sha'] = self.sha
            result = request_json(contents_url(source), token, 'PUT', payload)
            self.sha = result['content']['sha']
            return {'url': raw_url(source), 'sha': self.sha}
