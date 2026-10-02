import ast
import copy
import datetime as dt
import threading
import unittest
from pathlib import Path

from personal_timetable import apply_comci_result, comci_weekly_due, merge_comci_personal

MONDAY = dt.date(2026, 10, 5)


def fixture():
    return {
        'full': [{'name': '수업 전'}, {'name': '1교시'}, {'name': '점심 (1학년 5교시)'},
                 {'name': '5교시 (1학년 점심)'}, {'name': '7교시'}],
        'seven_period_days': [1, 2, 4],
        'comci_school_code': 123, 'comci_teacher_number': 4,
        'personal': {'1': [{'name': '아침지도', 'room': ''},
                           {'name': '예전 수업', 'room': '1-1', 'source': 'comci'},
                           {'name': '급식지도', 'room': '식당', 'source': 'manual'}]},
        'bg_color': '#abcdef',
    }


def remote():
    return {'personal': {str(d): [
        {'name': '국어', 'room': '2-3'}, {}, {}, {}, {'name': '수학', 'room': '1-2'}, {}, {'name': '영어', 'room': '3-1'}
    ] for d in range(1, 6)}, 'teacher_name': '테스트'}


class MergeTests(unittest.TestCase):
    def test_manual_lunch_legacy_and_automatic_lessons(self):
        data = fixture()
        original = copy.deepcopy(data)
        result = apply_comci_result(data, remote(), dt.datetime(2026, 10, 5, 8))
        rows = result['personal']['1']
        self.assertEqual(rows[0]['name'], '아침지도')
        self.assertEqual(rows[0]['source'], 'manual')
        self.assertEqual(rows[1]['name'], '국어')
        self.assertEqual(rows[1]['source'], 'comci')
        self.assertEqual(rows[2], data['personal']['1'][2])
        self.assertEqual(result['bg_color'], '#abcdef')
        self.assertEqual(data, original)

    def test_comci_merge_preserves_multiple_saved_special_profiles(self):
        data = fixture()
        data['special_schedules'] = [
            {'id': 'exam', 'name': '시험', 'dates': ['2026-10-15'], 'schedule': [{'name': '시험'}]},
            {'id': 'event', 'name': '행사', 'dates': ['2026-10-17'], 'schedule': [{'name': '행사'}]},
        ]
        result = apply_comci_result(data, remote(), dt.datetime(2026, 10, 5, 8))
        self.assertEqual(result['special_schedules'], data['special_schedules'])

    def test_empty_manual_override_is_preserved_and_unlocked_cell_updates(self):
        data = fixture()
        data['personal']['1'][1] = {'name': '', 'room': '', 'source': 'manual'}
        result = merge_comci_personal(data, remote()['personal'])
        self.assertEqual(result['1'][1]['name'], '')
        data['personal']['1'][1]['source'] = 'comci'
        self.assertEqual(merge_comci_personal(data, remote()['personal'])['1'][1]['name'], '국어')

    def test_deleted_comci_class_clears_only_import_owned_cell(self):
        result = remote(); result['personal']['1'][0] = {}
        merged = merge_comci_personal(fixture(), result['personal'])
        self.assertEqual(merged['1'][1]['name'], '')
        self.assertEqual(merged['1'][2]['name'], '급식지도')

    def test_six_period_days_and_joam_rule(self):
        data = fixture(); data['personal'] = {}; data['comci_joam_first_grade_fifth_period'] = True
        merged = merge_comci_personal(data, remote()['personal'])
        self.assertEqual(len(merged['3']), 4)
        self.assertEqual(merged['1'][2]['name'], '수학')
        self.assertEqual(merged['1'][3]['name'], '')
        data['personal'] = fixture()['personal']
        self.assertEqual(merge_comci_personal(data, remote()['personal'])['1'][2]['name'], '급식지도')

    def test_invalid_remote_does_not_produce_partial_merge(self):
        data = fixture(); before = copy.deepcopy(data)
        with self.assertRaises(ValueError): merge_comci_personal(data, {'1': []})
        self.assertEqual(data, before)

    def test_populated_legacy_class_is_preserved_until_unlocked(self):
        data = fixture(); data['personal']['1'][1].pop('source')
        self.assertEqual(merge_comci_personal(data, remote()['personal'])['1'][1]['name'], '예전 수업')

    def test_weekly_due_only_monday_once_per_target(self):
        data = fixture()
        self.assertTrue(comci_weekly_due(data, MONDAY))
        for offset in range(1, 7):
            self.assertFalse(comci_weekly_due(data, MONDAY + dt.timedelta(days=offset)))
        data = apply_comci_result(data, remote(), dt.datetime(2026, 10, 5, 8))
        self.assertFalse(comci_weekly_due(data, MONDAY))
        self.assertTrue(comci_weekly_due(data, MONDAY + dt.timedelta(days=7)))
        data['comci_teacher_number'] = 5
        self.assertTrue(comci_weekly_due(data, MONDAY))
        data['comci_weekly_auto_enabled'] = False
        self.assertFalse(comci_weekly_due(data, MONDAY))
        data = fixture(); data['comci_school_code'] = None
        self.assertFalse(comci_weekly_due(data, MONDAY))


class WeeklyApiTests(unittest.TestCase):
    """Exercise the production API method without starting a native webview."""
    def setUp(self):
        tree = ast.parse((Path(__file__).parents[1] / 'whattime_app.py').read_text())
        api = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Api')
        method = next(node for node in api.body if isinstance(node, ast.FunctionDef) and node.name == 'sync_weekly_comci')
        cls = ast.ClassDef(name='ApiUnderTest', bases=[], keywords=[], body=[method], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
        self.data = fixture(); self.calls = 0
        def fetch(*args):
            self.calls += 1
            return remote()
        self.env = {'SCHEDULE_LOCK': threading.RLock(), 'load_schedule': lambda: copy.deepcopy(self.data),
                    'save_schedule': self.save, 'comci_weekly_due': lambda data: comci_weekly_due(data, MONDAY),
                    'comci_target': lambda data: (data['comci_school_code'], data['comci_teacher_number']),
                    'fetch_comci_teacher_schedule': fetch,
                    'apply_comci_result': lambda data, result: apply_comci_result(data, result, dt.datetime(2026,10,5,8))}
        exec(compile(module, 'weekly-api-test', 'exec'), self.env)
        self.api = self.env['ApiUnderTest']()
        self.api._comci_sync_lock = threading.Lock()
        self.api._settings_window = None; self.api._settings_opening = False

    def save(self, data):
        self.data = copy.deepcopy(data)

    def test_success_once_and_personal_preservation(self):
        self.assertTrue(self.api.sync_weekly_comci()['updated'])
        self.assertFalse(self.api.sync_weekly_comci()['updated'])
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.data['personal']['1'][2]['name'], '급식지도')

    def test_failure_keeps_schedule_and_remains_due(self):
        before = copy.deepcopy(self.data['personal'])
        def fail(*args): raise OSError('offline')
        self.env['fetch_comci_teacher_schedule'] = fail
        self.assertFalse(self.api.sync_weekly_comci()['ok'])
        self.assertEqual(self.data['personal'], before)
        self.assertTrue(comci_weekly_due(self.data, MONDAY))

    def test_settings_edit_defers_network_and_commit(self):
        self.api._settings_window = object()
        self.assertTrue(self.api.sync_weekly_comci()['deferred'])
        self.assertEqual(self.calls, 0)
        self.api._settings_window = None
        def fetch(*args):
            self.api._settings_window = object()
            return remote()
        self.env['fetch_comci_teacher_schedule'] = fetch
        self.assertTrue(self.api.sync_weekly_comci()['deferred'])
        self.assertNotIn('comci_last_sync', self.data)

    def test_merges_latest_settings_after_network(self):
        def fetch(*args):
            self.data['bg_color'] = '#123456'
            self.data['personal']['1'][1] = {'name': '긴급지도', 'room': '', 'source': 'manual'}
            return remote()
        self.env['fetch_comci_teacher_schedule'] = fetch
        self.api.sync_weekly_comci()
        self.assertEqual(self.data['bg_color'], '#123456')
        self.assertEqual(self.data['personal']['1'][1]['name'], '긴급지도')


if __name__ == '__main__':
    unittest.main()
