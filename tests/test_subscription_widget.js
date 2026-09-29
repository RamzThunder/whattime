// Run with node tests/test_subscription_widget.js; no third-party dependencies.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');
for (const file of ['whattime.html', 'settings.html', 'schedule_admin.html', 'desktop_reminder.html']) {
    const html = fs.readFileSync(path.join(root, file), 'utf8');
    for (const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(script[1], {filename: file});
}
const html = fs.readFileSync(path.join(root, 'whattime.html'), 'utf8');
const functions = html.slice(html.indexOf('function deriveSixPeriodSchedule('), html.indexOf('function toMinutes('));
const context = vm.createContext({assert});
vm.runInContext(fs.readFileSync(path.join(root,'lesson_mapping.js'),'utf8'),context);
vm.runInContext(functions + `
const ordinary = [{name:'수업 전',start:'08:00',end:'08:40'}, {name:'1교시',start:'09:00',end:'09:45'}, {name:'2교시',start:'10:00',end:'10:45'}];
const special = [{name:'1교시',start:'09:00',end:'09:30'}];
const day = new Date(2026,9,15);
let scheduleData = {full:ordinary, seven_period_days:[1,2,4], rest_days:[0,6], special_schedule_enabled:false,
    subscribed_school:{name:'학교',events:[{date:'2026-10-15',title:'단축',periods:special}, {date:'2026-10-17',title:'토요일 행사',periods:special}]},
    personal:{'4':[{name:''},{name:'국어',room:'1-1'},{name:'수학',room:'1-2'}]}};
assert.equal(getTodaySchedule(day),special, 'subscription applies without experimental toggle');
assert.equal(getTodaySchedule(new Date(2026,9,16)),ordinary, 'ordinary day is unchanged');
assert.equal(getTodaySchedule(new Date(2026,9,17)),special, 'published Saturday overrides rest day');
assert.equal(getTodaySchedule(new Date(2026,9,18)).length,0, 'unpublished Sunday stays empty');
assert.equal(subscribedPersonalEntry(special[0],day).name,'국어', 'omitted morning row cannot shift personal lessons');
assert.equal(subscribedPersonalEntry({name:'행사'},day),undefined, 'new event has no arbitrary personal lesson');
scheduleData.special_schedule_enabled=true;scheduleData.special_dates=['2026-10-15'];scheduleData.special=[{name:'내 설정'}];
assert.equal(getTodaySchedule(day),scheduleData.special, 'local exception wins');
const profileA = [{name:'시험 시정'}], profileB = [{name:'행사 시정'}];
scheduleData.special_schedules=[
    {id:'exam',dates:['2026-10-15'],schedule:profileA},
    {id:'event',dates:['2026-10-17'],schedule:profileB}
];
assert.equal(getTodaySchedule(day),profileA,'v2.2.4 saved profile wins over subscription and legacy schedule');
assert.equal(getTodaySchedule(new Date(2026,9,17)),profileB,'second saved profile applies on its own date, including Saturday');
scheduleData.special_schedules[0].dates=['2026-10-16'];
assert.equal(getTodaySchedule(day),special,'unassigned legacy dates cannot shadow the active profile library or subscription');
scheduleData.special_schedule_enabled=false;scheduleData.subscribed_school.events=[];
assert.equal(getTodaySchedule(day),ordinary, 'cancelled event restores ordinary schedule');
scheduleData.subscribed_school=null;
assert.equal(getTodaySchedule(day),ordinary, 'unsubscribing restores ordinary schedule');
assert.ok(!formatPeriodName('<img src=x onerror=alert(1)>').includes('<img'), 'remote names render as text');
assert.equal(formatPeriodName('점심 (행사)'), '점심 <span class="sub-label">(행사)</span>');
`, context);
console.log('Widget subscription behavior and HTML JavaScript syntax passed.');

(async () => {
    let currentDate = new Date(2026, 9, 5, 8);
    class ClockDate extends Date {
        constructor(...args) { super(...(args.length ? args : [currentDate.getTime()])); }
    }
    const counts = {check:0, accept:0, decline:0, prompt:0, weekly:0, reload:0};
    let consent = false, subscribed = true;
    let proposal = {ok:true, proposal_id:'candidate', requires_confirmation:true, school_name:'학교', changes:['2026-10-15 변경']};
    let weeklyResult = {ok:true, updated:true};
    const status = {};
    const api = {
        get_school_subscription:async()=>({school_id:subscribed?'school-a':''}),
        check_school_subscription:async()=>{counts.check++;return proposal;},
        accept_school_subscription:async()=>{counts.accept++;},
        decline_school_subscription:async()=>{counts.decline++;},
        sync_weekly_comci:async()=>{counts.weekly++;return weeklyResult;},
    };
    const flowContext = vm.createContext({Date:ClockDate, window:{pywebview:{api}},
        document:{getElementById:()=>status}, confirmSchoolSubscription:async()=>{counts.prompt++;return consent;},
        loadSchedule:async()=>{}, reloadSchedule:async()=>{counts.reload++;},
        setTimeout:()=>{}, console});
    const dateFunction = html.slice(html.indexOf('function localDateKey('),html.indexOf('function publishedEvent('));
    const flowFunctions = html.slice(html.indexOf('async function checkSchoolSubscriptionAtStartup('),html.indexOf('function scheduleRender('));
    vm.runInContext(dateFunction + flowFunctions,flowContext);
    await vm.runInContext('checkSchoolSubscriptionAtStartup()',flowContext);
    assert.equal(counts.accept,0,'declining must not apply');assert.equal(counts.decline,1);
    consent=true;
    await vm.runInContext('checkSchoolSubscriptionAtStartup()',flowContext);
    assert.equal(counts.accept,1,'accept applies the proposal');
    proposal={...proposal,requires_confirmation:false,changes:[]};
    await vm.runInContext('checkSchoolSubscriptionAtStartup()',flowContext);
    assert.equal(counts.prompt,2,'unchanged schedules do not prompt');
    subscribed=false;
    await vm.runInContext('checkSchoolSubscriptionAtStartup()',flowContext);
    assert.equal(counts.check,3,'unsubscribed app does not fetch');
    await vm.runInContext('checkWeeklyComci()',flowContext);
    await vm.runInContext('checkWeeklyComci()',flowContext);
    assert.equal(counts.weekly,1,'repeated same-day ticks do not hit the network');
    currentDate=new Date(2026,9,6,8);
    await vm.runInContext('checkWeeklyComci()',flowContext);
    assert.equal(counts.weekly,1,'Tuesday does not sync');
    currentDate=new Date(2026,9,12,8);weeklyResult={ok:true,deferred:true};
    await vm.runInContext('checkWeeklyComci()',flowContext);
    weeklyResult={ok:true,updated:true};
    await vm.runInContext('checkWeeklyComci()',flowContext);
    assert.equal(counts.weekly,3,'deferred Monday sync retries after editing closes');
    assert.equal(counts.reload,2,'only completed updates reload the widget');
    console.log('Startup consent and Monday refresh flow passed.');
})().catch(error => {console.error(error);process.exitCode=1;});
