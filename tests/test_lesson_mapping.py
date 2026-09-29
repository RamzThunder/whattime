import copy
import datetime as dt
import unittest
from lesson_mapping import resolve_personal, special_scope
from desktop_reminders import current_lesson
from school_schedules import validate_feed
from personal_timetable import apply_comci_result

DATE=dt.date(2026,9,29)
def fixture():
    rows=[{'id':'early','name':'3학년 6교시 (1·2학년 급식)','start':'11:45','end':'12:35','lesson_period':6,'grades':[3]},
          {'id':'late','name':'이름을 바꾼 수업','start':'12:35','end':'13:10','lesson_period':6,'grades':[1,2]}]
    data={'seven_period_days':[1,2,4],'full':[{'name':'아침활동'},{'name':'6교시'}],
          'personal':{'2':[{}, {'name':'국어','room':'3-4','source':'comci'}]},
          'special_schedule_enabled':True,'special_schedules':[{'id':'p','dates':[DATE.isoformat()],'schedule':rows}]}
    return data, rows

class MappingTests(unittest.TestCase):
    def test_local_and_published_use_same_link_and_grade(self):
        data,rows=fixture()
        for scope in ['local:p','school:s']:
            self.assertEqual(resolve_personal(data,DATE,scope,rows[0])['room'],'3-4')
            self.assertEqual(resolve_personal(data,DATE,scope,rows[1]),{})
            data['personal']['2'][1]['room']='1-4'
            self.assertEqual(resolve_personal(data,DATE,scope,rows[0]),{})
            self.assertEqual(resolve_personal(data,DATE,scope,rows[1])['room'],'1-4')
            data['personal']['2'][1]['room']='3-4'

    def test_renaming_reordering_and_time_change_keep_override_by_id(self):
        data,rows=fixture()
        data['special_personal_overrides']={DATE.isoformat():{'local:p':{'early':{'mode':'custom','name':'감독','room':'3-1'}}}}
        rows[0]['name']='시험';rows[0]['start']='10:00';rows.reverse()
        self.assertEqual(resolve_personal(data,DATE,'local:p',rows[1]),{'name':'감독','room':'3-1'})
        self.assertEqual(resolve_personal(data,DATE,'school:s',rows[1])['room'],'3-4')
        data['special_personal_overrides'][DATE.isoformat()]['local:p']['early']['mode']='none'
        self.assertEqual(resolve_personal(data,DATE,'local:p',rows[1]),{})

    def test_legacy_names_with_spaces_and_unknown_room(self):
        data,rows=fixture()
        self.assertEqual(resolve_personal(data,DATE,'local:p',{'name':'제 6 교시'})['room'],'3-4')
        self.assertEqual(resolve_personal(data,DATE,'local:p',{'name':'3학년 6교시'})['room'],'3-4')
        self.assertEqual(resolve_personal(data,DATE,'local:p',{'name':'6교시 (3학년 급식)'}),{})
        self.assertEqual(resolve_personal(data,DATE,'local:p',{'name':'행사'}),{})
        data['personal']['2'][1]['room']='강당'
        self.assertEqual(resolve_personal(data,DATE,'local:p',rows[0]),{})

    def test_per_date_override_and_school_scope_isolation(self):
        data,rows=fixture()
        data['special_personal_overrides']={DATE.isoformat():{'local:p':{'early':{'mode':'none'}}}}
        other=DATE+dt.timedelta(days=7)
        self.assertEqual(resolve_personal(data,other,'local:p',rows[0])['room'],'3-4')
        school={'id':'s','events':[{'date':DATE.isoformat(),'periods':rows}]}
        self.assertEqual(special_scope(data,school,DATE)[0],'local:p')
        data['special_schedule_enabled']=False
        self.assertEqual(special_scope(data,school,DATE)[0],'school:s')

    def test_reminder_uses_renamed_local_and_published_rows(self):
        data,rows=fixture();rows[0]['name']='시험 마치고 수업'
        self.assertEqual(current_lesson(data,None,dt.datetime(2026,9,29,12,0))['class_name'],'3-4')
        self.assertIsNone(current_lesson(data,None,dt.datetime(2026,9,29,12,40)))
        data['special_schedule_enabled']=False
        school={'id':'s','events':[{'date':DATE.isoformat(),'periods':rows}]}
        self.assertEqual(current_lesson(data,school,dt.datetime(2026,9,29,12,0))['class_name'],'3-4')

    def test_publishing_preserves_links_and_rejects_invalid_values(self):
        _,rows=fixture()
        feed={'version':1,'schools':[{'id':'s','name':'학교','events':[{'date':DATE.isoformat(),'title':'단축','periods':rows}]}]}
        self.assertEqual(validate_feed(feed)['schools'][0]['events'][0]['periods'][0]['lesson_period'],6)
        for key,value in [('lesson_period',True),('lesson_period',13),('grades',[]),('grades',[4]),('grades',[1,1])]:
            bad=copy.deepcopy(feed);bad['schools'][0]['events'][0]['periods'][0][key]=value
            with self.assertRaises(ValueError):validate_feed(bad)

    def test_comci_refresh_preserves_date_overrides_and_links(self):
        data,rows=fixture();data['comci_school_code']=1;data['comci_teacher_number']=1
        data['special_personal_overrides']={DATE.isoformat():{'local:p':{'early':{'mode':'custom','name':'감독','room':'3-1'}}}}
        incoming={'personal':{str(day):[{}, {}, {}, {}, {}, {'name':'수학','room':'3-7'}] for day in range(1,6)}}
        updated=apply_comci_result(data,incoming)
        self.assertEqual(updated['special_personal_overrides'],data['special_personal_overrides'])
        self.assertEqual(updated['special_schedules'],data['special_schedules'])
        self.assertEqual(resolve_personal(updated,DATE,'local:p',rows[0])['room'],'3-1')
        del updated['special_personal_overrides']
        self.assertEqual(resolve_personal(updated,DATE,'local:p',rows[0])['room'],'3-7')

    def test_first_grade_fifth_lunch_rule_preserved(self):
        data,_=fixture();data['comci_joam_first_grade_fifth_period']=True
        data['full']=[{'name':'점심 (1학년 5교시)'},{'name':'5교시 (1학년 점심)'}]
        data['personal']['2']=[{'name':'영어','room':'1-2'},{}]
        entry=resolve_personal(data,DATE,'local:p',{'name':'특별 수업','lesson_period':5,'grades':[1]})
        self.assertEqual(entry['room'],'1-2')
