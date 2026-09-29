/* Shared by the widget and settings; names are presentation, links are explicit. */
const LessonMapping = (() => {
    const dateKey = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
    function inferred(item) {
        const name=String(item.name || '').trim();
        if(/점심.*1학년\s*5교시/.test(name))return {lesson_period:5,grades:[1]};
        const match=name.match(/^(?:([1-3])학년\s*)?(?:제\s*)?(\d+)\s*교시/);
        let grades=match?.[1]?[Number(match[1])]:[1,2,3];
        const lunch=name.match(/\(([1-3])학년\s*(?:급식|점심)\)/);
        if(lunch) grades=grades.filter(n=>n!==Number(lunch[1]));
        return {lesson_period:match?Number(match[2]):0,grades};
    }
    function link(item) {
        const guess=inferred(item);
        return {lesson_period:Number.isInteger(item.lesson_period)?item.lesson_period:guess.lesson_period,
            grades:Array.isArray(item.grades)?item.grades:guess.grades};
    }
    function scope(data,date) {
        const key=dateKey(date);
        if(data.special_schedule_enabled !== false) {
            const profiles=data.special_schedules || [];
            const p=profiles.find(p=>p.dates?.includes(key)&&p.schedule?.length);
            if(p)return {id:'local:'+p.id,rows:p.schedule,name:p.name};
            if(!profiles.length && data.special_dates?.includes(key) && data.special?.length)
                return {id:'local:legacy',rows:data.special,name:'특별 시정'};
        }
        const school=data.subscribed_school;
        const event=school?.events?.find(e=>e.date===key);
        return event?{id:'school:'+school.id,rows:event.periods,name:event.title}:null;
    }
    const rowKey=item=>item.id || JSON.stringify([item.name||'',item.start||'',item.end||'']);
    function override(data,date,context,item) {
        return data.special_personal_overrides?.[dateKey(date)]?.[context.id]?.[rowKey(item)] || {};
    }
    function ordinary(data,date) {
        const full=data.full || [];
        return (data.seven_period_days || [1,2,4]).includes(date.getDay())?full:full.filter(p=>!/^\s*7교시/.test(p.name||''));
    }
    function resolve(data,date,context,item) {
        const own=override(data,date,context,item);
        if(own.mode==='none')return undefined;
        if(own.mode==='custom')return {name:own.name||'',room:own.room||''};
        const mapping=link({...item,...own});
        const entries=data.personal?.[String(date.getDay())] || [];
        const base=ordinary(data,date);
        let index=-1;
        if(mapping.lesson_period) {
            const candidates=base.map((row,i)=>({row,i})).filter(({row})=>inferred(row).lesson_period===mapping.lesson_period);
            // Preserve the existing first-grade fifth-period lunch placement.
            if(mapping.lesson_period===5 && data.comci_joam_first_grade_fifth_period) {
                const lunch=base.findIndex(row=>/점심/.test(row.name||'')&&/1학년 5교시/.test(row.name||''));
                if(lunch>=0 && /^1-/.test(entries[lunch]?.room||''))index=lunch;
            }
            if(index<0)index=candidates[0]?.i ?? -1;
        } else if(!Object.hasOwn(item,'lesson_period')&&!Object.hasOwn(own,'lesson_period')) {
            index=base.findIndex(row=>row.name===item.name);
        }
        const entry=entries[index];
        if(!entry)return undefined;
        const grade=String(entry.room||'').trim().match(/^([1-3])(?:\s*-|학년)/)?.[1];
        if(mapping.grades.length!==3 && (!grade||!mapping.grades.includes(Number(grade))))return undefined;
        return entry;
    }
    function freeze(item) {
        const value=link(item);item.lesson_period=value.lesson_period;item.grades=[...value.grades];
        if(!item.id)item.id='row-'+(globalThis.crypto?.randomUUID?.() || Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
    }
    return {dateKey,inferred,link,scope,rowKey,override,resolve,freeze};
})();
