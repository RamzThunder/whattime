const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname,'..','schedule_admin.html'),'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
    constructor(){this.children=[];this.style={};this.value='';}
    add(item){this.children.push(item);}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=[...items];}
    setAttribute(key,value){this[key]=value;}
}
const elements = {};
const context = vm.createContext({assert,console,Option:class {constructor(text,value){this.text=text;this.value=value;}},document:{createTextNode:text=>text,getElementById:id=>elements[id] ||= new Element(),createElement:()=>new Element()},window:{addEventListener:()=>{}},confirm:()=>true});
vm.runInContext(fs.readFileSync(path.join(__dirname,'..','lesson_mapping.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'..','lesson_mapping_editor.js'),'utf8'),context);
vm.runInContext(source+`
feed={version:1,schools:[{id:'demo',name:'학교',events:[]}]};schoolIndex=0;
newEvent();
assert.equal(event().periods[0].name,'아침활동 및 학급조회');
assert.equal(event().periods[0].start,'08:20');
assert.equal(event().periods[1].name,'1교시');
assert.equal($('periods').children[0].children[0].children[0].readOnly,true);
assert.equal($('periods').children[0].children[1].children[0].readOnly,true);
assert.equal($('periods').children[0].children[4].children[0].disabled,true);
addPeriod();assert.equal(event().periods[2].name,'2교시');
const endInput=$('periods').children[2].children[2].children[0];
assert.equal(endInput.type,'text','time controls must not switch to AM/PM by OS locale');
endInput.value='1320';endInput.onblur();assert.equal(event().periods[1].end,'13:20');
assert.equal(normalizeTime24('8:20'),'08:20');assert.equal(normalizeTime24('820'),'08:20');
assert.equal(normalizeTime24('24:00'),'24:00','invalid times stay invalid for backend validation');
event().periods=[{name:'1교시',start:'09:00',end:'09:45'}];ensureMorning();
assert.equal(event().periods[0].end,'09:00','existing lesson times are preserved when adding the morning row');
ensureMorning();assert.equal(event().periods.length,2,'morning row is never duplicated');
`,context);
console.log('Admin morning row, numbering, and 24-hour input passed.');

vm.runInContext(`
event().preserve_first_row=true;
event().periods=[{name:MORNING_NAME,start:'09:00',end:'09:10'},{name:'1교시',start:'09:10',end:'09:50'}];
ensureMorning();renderPeriods();
assert.equal(event().periods[0].start,'09:00','imported morning start stays intact');
assert.notEqual($('periods').children[0].children[0].children[0].readOnly,true);
assert.equal($('periods').children[0].children[4].children[0].disabled,false);
addPeriod();assert.equal(event().periods[0].start,'09:00');
duplicateEvent();assert.equal(event().preserve_first_row,true);
event().periods.shift();ensureMorning();assert.equal(event().periods[0].name,'1교시');
`,context);
console.log('Imported first row remains editable after add, delete, and duplicate.');
vm.runInContext(`(async () => {
    loadedSource={repository:'test/test',branch:'main',path:'schedules.json'};
    const before=JSON.stringify(event());
    window.pywebview={api:{import_schedule_document:async()=>({ok:false,cancelled:true})}};
    await importDocument();assert.equal(JSON.stringify(event()),before);
    window.pywebview.api.import_schedule_document=async()=>({ok:false,error:'파일 오류'});
    await importDocument();assert.equal(JSON.stringify(event()),before);
    window.pywebview.api.import_schedule_document=async()=>({ok:true,filename:'test.hwp',periods:[{name:'1교시',start:'10:00',end:'10:40'}]});
    await importDocument();
    assert.equal(event().periods[0].start,'10:00');
    assert.equal(event().preserve_first_row,true);
    ensureMorning();assert.equal(event().periods.length,1);
})()`,context).then(()=>console.log('Admin document import, cancellation, and failure passed.')).catch(error=>{console.error(error);process.exitCode=1;});
