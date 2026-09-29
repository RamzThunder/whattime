import base64
import copy
import datetime as dt
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from school_schedules import (DEFAULT_SOURCE, GitHubPublisher, SubscriptionStore,
                              raw_url, source_config, validate_feed)


def fixture():
    return {'version': 1, 'schools': [{'id': 'school-a', 'name': '테스트학교', 'events': [
        {'date': '2026-10-15', 'title': '단축시정', 'periods': [
            {'name': '1교시', 'start': '09:00', 'end': '09:40'},
            {'name': '2교시', 'start': '09:50', 'end': '10:30'}]}]}]}


def accept_latest(store, source=None):
    result = store.check(source)
    return store.accept(result['proposal_id']) if result['ok'] else result['state']


class ValidationTests(unittest.TestCase):
    def test_normalizes_without_modifying_input(self):
        feed = fixture()
        validated = validate_feed(feed)
        self.assertFalse(validated['schools'][0]['events'][0]['periods'][0]['no_countdown'])
        self.assertNotIn('no_countdown', feed['schools'][0]['events'][0]['periods'][0])

    def test_rejects_invalid_dates_times_duplicates_and_schema(self):
        variants = []
        for key, value in [('date', '2026-02-30'), ('date', '20261015'), ('periods', []), ('title', '')]:
            feed = fixture(); feed['schools'][0]['events'][0][key] = value; variants.append(feed)
        for key, value in [('start', '9:00'), ('end', '08:00'), ('end', '25:00'), ('no_countdown', 'false')]:
            feed = fixture(); feed['schools'][0]['events'][0]['periods'][0][key] = value; variants.append(feed)
        feed = fixture(); feed['schools'][0]['events'][0]['periods'][1]['start'] = '09:30'; variants.append(feed)
        feed = fixture(); feed['schools'].append(copy.deepcopy(feed['schools'][0])); variants.append(feed)
        feed = fixture(); feed['schools'][0]['events'] *= 2; variants.append(feed)
        variants.extend([{}, [], {'version': 2, 'schools': []}])
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_feed(value)

    def test_imported_first_row_survives_validation_and_reload(self):
        feed = fixture()
        feed['schools'][0]['events'][0]['preserve_first_row'] = True
        result = validate_feed(validate_feed(feed))
        event = result['schools'][0]['events'][0]
        self.assertTrue(event['preserve_first_row'])
        self.assertEqual(event['periods'][0]['start'], '09:00')
        feed['schools'][0]['events'][0]['preserve_first_row'] = 'true'
        with self.assertRaises(ValueError): validate_feed(feed)

    def test_source_cannot_change_host_or_traverse(self):
        for repo in ['https://evil.test/a', 'owner/repo/extra', 'owner@evil/repo']:
            with self.assertRaises(ValueError):
                source_config({**DEFAULT_SOURCE, 'repository': repo})
        with self.assertRaises(ValueError):
            source_config({**DEFAULT_SOURCE, 'path': '../schedules.json'})
        self.assertTrue(raw_url(DEFAULT_SOURCE).startswith('https://raw.githubusercontent.com/'))


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'subscription.json')
        self.store = SubscriptionStore(self.path)

    def sync(self, feed=None):
        with patch('school_schedules.request_json', return_value=feed if feed is not None else fixture()):
            return accept_latest(self.store)

    def test_subscription_survives_restart_and_failed_network(self):
        self.sync(); self.store.select('school-a')
        recovered = SubscriptionStore(self.path)
        with patch('school_schedules.request_json', side_effect=URLError('offline')):
            state = recovered.check()['state']
        self.assertTrue(state['error'])
        self.assertTrue(state['last_success'])
        self.assertEqual(recovered.active_school()['id'], 'school-a')
        self.assertEqual(len(recovered.active_school()['events']), 1)

    def test_invalid_remote_does_not_replace_cached_feed(self):
        self.sync(); self.store.select('school-a')
        before = self.store.snapshot()['feed']
        self.assertTrue(self.sync({'version': 8})['error'])
        self.assertEqual(self.store.snapshot()['feed'], before)
        self.assertEqual(SubscriptionStore(self.path).snapshot()['feed'], before)

    def test_cancellation_and_unsubscribe(self):
        self.sync(); self.store.select('school-a')
        feed = fixture(); feed['schools'][0]['events'] = []
        self.sync(feed)
        self.assertEqual(self.store.active_school()['events'], [])
        self.store.select('')
        self.assertIsNone(self.store.active_school())
        self.assertEqual(len(self.store.snapshot()['feed']['schools']), 1)

    def test_deleted_school_stops_applying(self):
        self.sync(); self.store.select('school-a')
        self.sync({'version': 1, 'schools': []})
        self.assertIsNone(self.store.active_school())
        self.assertEqual(self.store.snapshot()['school_id'], 'school-a')

    def test_source_switch_only_commits_on_success(self):
        self.sync(); self.store.select('school-a')
        other = {**DEFAULT_SOURCE, 'repository': 'another/repo'}
        with patch('school_schedules.request_json', side_effect=URLError('offline')):
            accept_latest(self.store, other)
        self.assertEqual(self.store.snapshot()['source'], DEFAULT_SOURCE)
        self.assertEqual(self.store.active_school()['id'], 'school-a')
        with patch('school_schedules.request_json', return_value=fixture()):
            accept_latest(self.store, other)
        self.assertEqual(self.store.snapshot()['source'], other)
        self.assertIsNone(self.store.active_school())

    def test_unsubscribe_during_fetch_is_preserved(self):
        self.sync(); self.store.select('school-a')
        started, finish = threading.Event(), threading.Event()
        def fetch(*args):
            started.set(); self.assertTrue(finish.wait(3)); return fixture()
        with patch('school_schedules.request_json', side_effect=fetch):
            thread = threading.Thread(target=lambda: accept_latest(self.store))
            thread.start()
            self.assertTrue(started.wait(3))
            self.store.select(''); finish.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(self.store.active_school())

    def test_failed_disk_write_does_not_replace_active_schedule(self):
        self.sync(); self.store.select('school-a')
        with patch('school_schedules.atomic_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.sync({'version': 1, 'schools': []})
        self.assertIsNotNone(self.store.active_school())

    def test_fixed_source_discards_other_source_cache_and_ignores_override(self):
        other = {**DEFAULT_SOURCE, 'repository': 'another/repo'}
        with patch('school_schedules.request_json', return_value=fixture()):
            accept_latest(self.store, other)
        self.store.select('school-a')
        fixed = SubscriptionStore(self.path, fixed_source=DEFAULT_SOURCE)
        self.assertEqual(fixed.snapshot()['source'], DEFAULT_SOURCE)
        self.assertIsNone(fixed.active_school())
        with patch('school_schedules.request_json', return_value=fixture()) as request:
            fixed.check(other)
        self.assertEqual(request.call_args.args[0], raw_url(DEFAULT_SOURCE))

    def proposal(self, feed):
        with patch('school_schedules.request_json', return_value=feed):
            return self.store.check(today=dt.date(2026, 10, 1))

    def test_candidate_requires_acceptance_and_decline_keeps_cache(self):
        self.sync(); self.store.select('school-a')
        before = self.store.snapshot()
        feed = fixture(); feed['schools'][0]['events'][0]['periods'][0]['end'] = '09:35'
        result = self.proposal(feed)
        self.assertTrue(result['requires_confirmation'])
        self.assertIn('수정', result['changes'][0])
        self.assertEqual(self.store.snapshot()['feed'], before['feed'])
        self.assertEqual(SubscriptionStore(self.path).snapshot()['feed'], before['feed'])
        self.store.decline(result['proposal_id'])
        with self.assertRaises(ValueError): self.store.accept(result['proposal_id'])
        self.assertEqual(self.store.snapshot()['last_success'], before['last_success'])
        # A subsequent launch can offer the declined update again.
        result = self.proposal(feed)
        self.store.accept(result['proposal_id'])
        self.assertEqual(self.store.active_school()['events'][0]['periods'][0]['end'], '09:35')

    def test_unchanged_expired_and_other_school_changes_do_not_prompt(self):
        self.sync(); self.store.select('school-a')
        self.assertFalse(self.proposal(fixture())['requires_confirmation'])
        feed = fixture()
        other = copy.deepcopy(feed['schools'][0]); other['id'] = 'other'; feed['schools'].append(other)
        old = copy.deepcopy(feed['schools'][0]['events'][0]); old['date'] = '2026-01-01'
        feed['schools'][0]['events'].append(old)
        self.assertFalse(self.proposal(feed)['requires_confirmation'])

    def test_cancellation_prompts_and_stale_proposal_cannot_apply(self):
        self.sync(); self.store.select('school-a')
        feed = fixture(); feed['schools'][0]['events'] = []
        result = self.proposal(feed)
        self.assertTrue(result['requires_confirmation'])
        self.assertIn('취소', result['changes'][0])
        self.assertEqual(len(self.store.active_school()['events']), 1)
        self.store.select('')
        with self.assertRaises(ValueError): self.store.accept(result['proposal_id'])

    def test_approval_applies_the_previewed_version_without_refetch(self):
        self.sync(); self.store.select('school-a')
        feed = fixture(); feed['schools'][0]['events'][0]['title'] = '승인할 시정'
        result = self.proposal(feed)
        with patch('school_schedules.request_json', side_effect=AssertionError('must not fetch')):
            self.store.accept(result['proposal_id'])
        self.assertEqual(self.store.active_school()['events'][0]['title'], '승인할 시정')


class PublisherTests(unittest.TestCase):
    def load_existing(self, publisher):
        item = {'encoding': 'base64', 'sha': 'original',
                'content': base64.b64encode(json.dumps(fixture()).encode()).decode()}
        with patch('school_schedules.request_json', side_effect=[{'private': False}, {}, item]):
            publisher.load(DEFAULT_SOURCE, 'token')

    def test_updates_with_loaded_sha_and_refreshes_sha(self):
        publisher = GitHubPublisher(); self.load_existing(publisher)
        with patch('school_schedules.request_json', return_value={'content': {'sha': 'next'}}) as request:
            publisher.publish(DEFAULT_SOURCE, 'token', fixture())
        args = request.call_args.args
        self.assertEqual(args[2], 'PUT')
        self.assertEqual(args[3]['sha'], 'original')
        self.assertEqual(publisher.sha, 'next')
        self.assertEqual(json.loads(base64.b64decode(args[3]['content'])), validate_feed(fixture()))

    def test_new_file_omits_sha(self):
        publisher = GitHubPublisher()
        missing = HTTPError('url', 404, 'missing', {}, None)
        with patch('school_schedules.request_json', side_effect=[{'private': False}, {}, missing]):
            self.assertEqual(publisher.load(DEFAULT_SOURCE, 'token')['schools'], [])
        with patch('school_schedules.request_json', return_value={'content': {'sha': 'first'}}) as request:
            publisher.publish(DEFAULT_SOURCE, 'token', fixture())
        self.assertNotIn('sha', request.call_args.args[3])

    def test_missing_branch_is_not_treated_as_new_file(self):
        publisher = GitHubPublisher()
        with patch('school_schedules.request_json', side_effect=[{'private': False}, HTTPError('url', 404, '', {}, None)]):
            with self.assertRaises(HTTPError): publisher.load(DEFAULT_SOURCE, 'token')
        self.assertIsNone(publisher.source)

    def test_conflict_does_not_retry_or_overwrite(self):
        publisher = GitHubPublisher(); self.load_existing(publisher)
        with patch('school_schedules.request_json', side_effect=HTTPError('url', 409, '', {}, None)) as request:
            with self.assertRaises(HTTPError): publisher.publish(DEFAULT_SOURCE, 'token', fixture())
        self.assertEqual(request.call_count, 1)
        self.assertEqual(publisher.sha, 'original')

    def test_requires_loaded_public_repository_and_token(self):
        publisher = GitHubPublisher()
        with self.assertRaises(ValueError): publisher.publish(DEFAULT_SOURCE, 'token', fixture())
        with patch('school_schedules.request_json', return_value={'private': True}):
            with self.assertRaises(ValueError): publisher.load(DEFAULT_SOURCE, 'token')
        self.load_existing(publisher)
        with self.assertRaises(ValueError): publisher.publish(DEFAULT_SOURCE, '', fixture())
        with self.assertRaises(ValueError): publisher.publish({**DEFAULT_SOURCE, 'path': 'other.json'}, 'token', fixture())


if __name__ == '__main__':
    unittest.main()
