/* Small shared editor, used by the administrator and local special schedules. */
function lessonLinkEditor(item, changed) {
    const container=document.createElement('div');
    container.style.cssText='display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 12px;padding:8px;background:#f3f6f4;border-radius:8px;color:#25352c;';
    const current=LessonMapping.link(item);
    const period=document.createElement('select');
    period.setAttribute('aria-label','연결할 기본 교시');
    period.add(new Option('연결 없음','0'));
    for(let n=1;n<=12;n++)period.add(new Option(n+'교시',String(n)));
    period.value=String(current.lesson_period);
    const label=document.createElement('label');label.textContent='연결할 기본 교시 ';label.style.cssText='flex:1;min-width:115px;font-size:12px';label.append(period);container.append(label);
    const grades=document.createElement('div');grades.textContent='적용 학년 ';grades.style.cssText='display:flex;align-items:center;gap:6px;font-size:12px';
    const boxes=[];
    for(const n of [1,2,3]){const label=document.createElement('label');label.style.cssText='display:flex;align-items:center;gap:3px;white-space:nowrap';const input=document.createElement('input');input.type='checkbox';input.style.width='auto';input.checked=current.grades.includes(n);label.append(input,document.createTextNode(n+'학년'));grades.append(label);boxes.push([n,input]);input.onchange=()=>{if(!boxes.some(([,b])=>b.checked)){input.checked=true;return;}save();};}
    function save(){item.lesson_period=Number(period.value);item.grades=boxes.filter(([,b])=>b.checked).map(([n])=>n);changed();}
    period.onchange=save;container.append(grades);return container;
}
