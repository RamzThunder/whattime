import datetime as dt
import io
import unittest
import urllib.error

from notion_archive import (ACCOUNT, API_URL, SERVICE, archive_week, build_page, credentials, error_message,
                            parse_page_id, week_lessons)

PAGE_ID = '329059f492dd80ca87e0d59d7d581e1f'
NOW = dt.datetime(2026, 10, 6, 11, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))


def fixture():
    return {
        'full': [{'name': '학급 조회', 'start': '08:20', 'end': '08:35'},
                 {'name': '1교시', 'start': '08:40', 'end': '09:25'},
                 {'name': '점심 (1학년 5교시)', 'start': '12:15', 'end': '13:00'},
                 {'name': '5교시 (1학년 점심)', 'start': '13:00', 'end': '13:45'},
                 {'name': '7교시', 'start': '14:45', 'end': '15:30'}],
        'seven_period_days': [1, 2, 4],
        'comci_school_name': '테스트중', 'comci_joam_first_grade_fifth_period': True,
        'personal': {'5': [{}, {}, {'name': '급식지도', 'room': '', 'source': 'manual'}]},
        'notion_archive_page': f'https://www.notion.so/Archive-{PAGE_ID}?pvs=4',
    }


def remote():
    personal = {str(day): [{'name': '', 'room': ''} for _ in range(8)] for day in range(1, 6)}
    personal['2'][0] = {'name': '국어A', 'room': '3-12', 'changed': False}
    personal['2'][6] = {'name': '국어A', 'room': '3-2', 'changed': False}
    personal['3'][4] = {'name': '국어A', 'room': '3-4', 'changed': True}
    personal['3'][6] = {'name': '숨은 7교시', 'room': '3-1', 'changed': False}
    personal['4'][4] = {'name': '독서', 'room': '1-11', 'changed': False}
    return {'personal': personal, 'updated_at': '2026-10-06 11:01:16', 'school_name': '컴시간', 'school_name_hidden': True}


def plain(block):
    return ''.join(part['text']['content'] for part in block[block['type']]['rich_text'])


class Recorder:
    def __init__(self, fail_patch=False):
        self.calls = []
        self.fail_patch = fail_patch

    def __call__(self, url, token, payload, method='POST'):
        self.calls.append((method, url, token, payload))
        if method == 'PATCH' and self.fail_patch:
            raise urllib.error.HTTPError(url, 404, 'gone', {}, io.BytesIO())
        return {'id': 'new-page', 'url': 'https://notion.so/new-page'}


class PageIdTests(unittest.TestCase):
    def test_accepts_links_and_ids(self):
        dashed = '329059f4-92dd-80ca-87e0-d59d7d581e1f'
        for value in [PAGE_ID, dashed, f'https://app.notion.com/p/{PAGE_ID}?pvs=204',
                      f'https://www.notion.so/team/Deadbeef-cafe-{PAGE_ID}#block', f' {PAGE_ID.upper()}/ ']:
            self.assertEqual(parse_page_id(value), PAGE_ID)

    def test_rejects_values_without_an_id(self):
        for value in ['', None, 'https://www.notion.so/', '자료 아카이빙']:
            with self.assertRaises(ValueError):
                parse_page_id(value)


class PageTests(unittest.TestCase):
    def test_lessons_follow_the_app_layout(self):
        week = week_lessons(fixture(), remote())
        self.assertEqual(week[1], [])
        self.assertEqual([(l['row'], l['room']) for l in week[2]], [('1교시', '3-12'), ('7교시', '3-2')])
        # Wednesday has no seventh period, and a non-first-grade fifth period stays after lunch.
        self.assertEqual([(l['row'], l['name'], l['changed']) for l in week[3]], [('5교시 (1학년 점심)', '국어A', True)])
        self.assertEqual([(l['row'], l['name']) for l in week[4]], [('점심 (1학년 5교시)', '독서')])
        self.assertEqual([(l['name'], l['changed']) for l in week[5]], [('급식지도', False)])

    def test_page_lists_table_and_days(self):
        page = build_page(fixture(), remote(), dt.date(2026, 10, 5), PAGE_ID)
        self.assertEqual(page['parent'], {'type': 'page_id', 'page_id': PAGE_ID})
        self.assertEqual(page['properties']['title']['title'][0]['text']['content'], '수업 시간표 2026.10.05~10.09')
        blocks = page['children']
        self.assertLessEqual(len(blocks), 100)
        self.assertEqual(plain(blocks[0]), '테스트중 · 컴시간 2026-10-06 11:01:16 기준 · WhatTime에서 자동 보관')
        table = next(b for b in blocks if b['type'] == 'table')['table']
        rows = [[''.join(p['text']['content'] for p in cell) for cell in row['table_row']['cells']]
                for row in table['children']]
        self.assertEqual(rows, [
            ['교시', '월 10/5', '화 10/6', '수 10/7', '목 10/8', '금 10/9'],
            ['1교시 08:40–09:25', '', '국어A 3-12', '', '', ''],
            ['점심 12:15–13:00', '', '', '', '독서 1-11', '급식지도'],
            ['5교시 13:00–13:45', '', '', '국어A 3-4 🔄', '', ''],
            ['7교시 14:45–15:30', '', '국어A 3-2', '', '', ''],
        ])
        self.assertTrue(all(len(row['table_row']['cells']) == table['table_width'] for row in table['children']))
        lines = [plain(b) for b in blocks if b['type'] != 'table']
        self.assertIn('월 10/5', lines)
        self.assertEqual(lines[lines.index('월 10/5') + 1], '수업 없음')
        self.assertIn('화 10/6 · 수업 2시간', lines)
        self.assertIn('5교시 13:00–13:45 · 국어A · 3-4 🔄', lines)
        self.assertIn('금 10/9', lines)
        self.assertIn('점심 12:15–13:00 · 급식지도', lines)

    def test_empty_week_has_no_table(self):
        data = fixture()
        data['personal'] = {}
        result = remote()
        result['personal'] = {str(day): [] for day in range(1, 6)}
        blocks = build_page(data, result, dt.date(2026, 10, 5), PAGE_ID)['children']
        self.assertFalse(any(b['type'] == 'table' for b in blocks))
        self.assertIn('이번 주 수업 없음', [plain(b) for b in blocks])


class ArchiveTests(unittest.TestCase):
    def test_first_archive_creates_one_page(self):
        send = Recorder()
        record = archive_week(fixture(), remote(), 'token', NOW, send)
        self.assertEqual(record, {'week': '2026-10-05', 'page_id': 'new-page', 'url': 'https://notion.so/new-page',
                                  'at': '2026-10-06T11:00:00+09:00'})
        self.assertEqual([(c[0], c[1], c[2]) for c in send.calls], [('POST', API_URL, 'token')])

    def test_same_week_replaces_and_other_weeks_accumulate(self):
        data = fixture()
        data['notion_last_archive'] = {'week': '2026-10-05', 'page_id': 'old-page'}
        send = Recorder()
        archive_week(data, remote(), 'token', NOW, send)
        self.assertEqual(send.calls[1][:2], ('PATCH', API_URL + '/old-page'))
        self.assertEqual(send.calls[1][3], {'archived': True})

        data['notion_last_archive']['week'] = '2026-09-28'
        send = Recorder()
        archive_week(data, remote(), 'token', NOW, send)
        self.assertEqual([c[0] for c in send.calls], ['POST'])

    def test_missing_old_page_does_not_fail_the_archive(self):
        data = fixture()
        data['notion_last_archive'] = {'week': '2026-10-05', 'page_id': 'old-page'}
        self.assertEqual(archive_week(data, remote(), 'token', NOW, Recorder(fail_patch=True))['page_id'], 'new-page')

    def test_requires_token_and_page_before_any_request(self):
        send = Recorder()
        with self.assertRaises(ValueError):
            archive_week(fixture(), remote(), '', NOW, send)
        data = fixture()
        data['notion_archive_page'] = ''
        with self.assertRaises(ValueError):
            archive_week(data, remote(), 'token', NOW, send)
        self.assertEqual(send.calls, [])

    def test_error_messages_do_not_leak_details(self):
        missing = urllib.error.HTTPError(API_URL, 404, 'secret-marker', {}, io.BytesIO())
        self.assertIn('통합을 연결', error_message(missing))
        self.assertNotIn('secret-marker', error_message(RuntimeError('secret-marker')))
        self.assertEqual(error_message(ValueError('안내')), '안내')


class CredentialTests(unittest.TestCase):
    def test_token_uses_its_own_vault_entry(self):
        class Vault(dict):
            def get_password(self, service, account): return self.get((service, account))
            def set_password(self, service, account, password): self[service, account] = password
        vault = Vault()
        credentials(vault).save(' notion-test-token ')
        self.assertEqual(dict(vault), {(SERVICE, ACCOUNT): 'notion-test-token'})


if __name__ == '__main__':
    unittest.main()
