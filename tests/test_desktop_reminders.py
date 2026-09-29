import datetime as dt
import unittest

from desktop_reminders import ReminderEngine, current_lesson


def lesson(start=1000, name='1-2'):
    return {'id': f'lesson:{start}:{name}', 'start_ts': start, 'end_ts': start+2700,
            'class_name': name, 'subject': '국어', 'period': '1교시', 'start': '08:40', 'end': '09:25'}


def settings():
    return {'full': [{'name': '아침활동 및 학급조회', 'start': '08:20', 'end': '08:40'},
                     {'name': '1교시', 'start': '08:40', 'end': '09:25'},
                     {'name': '2교시', 'start': '09:35', 'end': '10:20'},
                     {'name': '점심 (1학년 5교시)', 'start': '12:15', 'end': '13:00'}],
            'seven_period_days': [1,2,4], 'rest_days': [0,6],
            'personal': {'1': [{}, {'name': '국어', 'room': '1-2'}, {'name': '수학', 'room': '2-3'},
                               {'name': '급식지도', 'room': '식당'}]}}


class ReminderEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ReminderEngine()
        self.lesson = lesson()

    def test_start_once_then_red_only_after_input_at_twenty_seconds(self):
        self.assertEqual(self.engine.tick(self.lesson, 1000)['level'], 'start')
        self.assertIsNone(self.engine.tick(self.lesson, 1001, 0))
        self.assertIsNone(self.engine.tick(self.lesson, 1019.9, 0))
        self.assertIsNone(self.engine.tick(self.lesson, 1020, 2))
        self.assertEqual(self.engine.tick(self.lesson, 1020.2, 0)['level'], 'urgent')
        self.assertIsNone(self.engine.tick(self.lesson, 1021, 0))
        self.assertIsNone(self.engine.tick(self.lesson, 1100, 0))

    def test_idle_user_or_unavailable_sensor_never_gets_red(self):
        self.engine.tick(self.lesson, 1000)
        for now, idle in [(1020, 20), (1050, 50), (1051, None), (1052, float('nan')), (1053,-1)]:
            self.assertIsNone(self.engine.tick(self.lesson, now, idle))

    def test_closing_popup_alone_does_not_trigger_red(self):
        self.engine.tick(self.lesson, 1000)
        self.engine.dismiss(self.lesson['id'], 1021)
        self.assertIsNone(self.engine.tick(self.lesson, 1021.5, 0))
        self.assertIsNone(self.engine.tick(self.lesson, 1023, 2))
        self.assertEqual(self.engine.tick(self.lesson, 1024, 0)['level'], 'urgent')

    def test_mute_survives_returning_to_computer_and_next_lesson_still_alerts(self):
        self.engine.tick(self.lesson, 1000)
        self.engine.dismiss(self.lesson['id'], 1005, mute=True)
        for now in [1020, 1300, 2400]:
            self.assertIsNone(self.engine.tick(self.lesson, now, 0))
        next_lesson = lesson(4000, '3-1')
        self.assertEqual(self.engine.tick(next_lesson, 4000)['level'], 'start')
        self.assertEqual(self.engine.tick(next_lesson, 4020, 0)['level'], 'urgent')

    def test_mute_from_red_popup_stays_muted(self):
        self.engine.tick(self.lesson, 1000)
        self.engine.tick(self.lesson, 1020, 0)
        self.engine.dismiss(self.lesson['id'], 1021, mute=True)
        self.assertIsNone(self.engine.tick(self.lesson, 1200, 0))

    def test_no_stale_notifications_on_launch_halfway_through_class(self):
        self.assertIsNone(self.engine.tick(self.lesson, 1500, 0))
        self.assertIsNone(self.engine.tick(self.lesson, 1501, 0))
        self.assertIsNone(self.engine.tick(lesson(5000), 4999, 0))
        self.assertEqual(self.engine.tick(lesson(5000), 5000, 0)['level'], 'start')

    def test_no_notification_outside_lesson(self):
        self.assertIsNone(self.engine.tick(None, 1000, 0))
        self.engine.tick(self.lesson, 1000)
        self.assertIsNone(self.engine.tick(self.lesson, self.lesson['end_ts'], 0))


class LessonResolverTests(unittest.TestCase):
    def test_normal_lesson_independent_of_progress_feature(self):
        data = settings(); data['progress_auto_save'] = False
        current = current_lesson(data, None, dt.datetime(2026,10,5,8,40))
        self.assertEqual(current['class_name'], '1-2')
        self.assertEqual(current['subject'], '국어')
        self.assertIsNone(current_lesson(data, None, dt.datetime(2026,10,5,9,25)))
        self.assertIsNone(current_lesson(data, None, dt.datetime(2026,10,5,8,20)))

    def test_no_lunch_duty_or_class_without_room_alert(self):
        data = settings()
        self.assertIsNone(current_lesson(data, None, dt.datetime(2026,10,5,12,15)))
        data['personal']['1'][1]['room'] = ''
        self.assertIsNone(current_lesson(data, None, dt.datetime(2026,10,5,8,40)))

    def test_first_grade_lunch_lesson(self):
        data = settings(); data['comci_joam_first_grade_fifth_period'] = True
        data['personal']['1'][3] = {'name': '영어', 'room': '1-3'}
        self.assertEqual(current_lesson(data, None, dt.datetime(2026,10,5,12,15))['class_name'], '1-3')

    def test_subscribed_shortened_day_matches_period_numbers(self):
        data = settings()
        school = {'events': [{'date':'2026-10-05','periods':[{'name':'1교시','start':'09:00','end':'09:30'}]}]}
        self.assertIsNone(current_lesson(data, school, dt.datetime(2026,10,5,8,40)))
        current = current_lesson(data, school, dt.datetime(2026,10,5,9,0))
        self.assertEqual(current['class_name'], '1-2')
        self.assertEqual(current['start'], '09:00')

    def test_local_special_profile_overrides_subscription(self):
        data = settings(); data['special_schedule_enabled'] = True
        data['special_schedules'] = [{'dates':['2026-10-05'], 'schedule': [
            {'name':'수업 전','start':'08:20','end':'08:40'}, {'name':'1교시','start':'10:00','end':'10:40'}]}]
        school = {'events':[{'date':'2026-10-05','periods':[{'name':'1교시','start':'09:00','end':'09:30'}]}]}
        self.assertIsNone(current_lesson(data, school, dt.datetime(2026,10,5,9,0)))
        self.assertEqual(current_lesson(data, school, dt.datetime(2026,10,5,10,0))['start'],'10:00')

    def test_calibrated_clock_and_weekend(self):
        data=settings(); data['time_offset_seconds']=10
        current=current_lesson(data,None,dt.datetime(2026,10,5,8,39,50))
        self.assertEqual(current['start_ts'],dt.datetime(2026,10,5,8,39,50).timestamp())
        self.assertIsNone(current_lesson(data,None,dt.datetime(2026,10,4,8,40)))
