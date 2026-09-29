const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
class Element {
 constructor(){this.children=[];this.style={};this.events={};}
 setAttribute(){} append(...nodes){this.children.push(...nodes);}
 addEventListener(name,fn){this.events[name]=fn;}
 showModal(){this.open=true;} close(){this.open=false;this.events.close?.();}
 remove(){this.removed=true;} focus(){this.focused=true;}
 get firstElementChild(){return this.children[0];}
}
const body=new Element();
const context=vm.createContext({document:{body,createElement:()=>new Element()}});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../subscription_confirm.js'),'utf8'),context);
(async()=>{
 for(const action of ['later','accept','escape','close']){
  const promise=context.confirmSchoolSubscription({school_name:'<b>학교</b>',changes:['변경']});
  const dialog=body.children.at(-1), panel=dialog.children[0], buttons=panel.children[2].children;
  assert.equal(dialog.open,true);assert.equal(buttons[0].focused,true);
  assert.ok(panel.children[1].textContent.includes('<b>학교</b>'));
  if(action==='later')buttons[0].events.click();
  if(action==='accept')buttons[1].events.click();
  if(action==='escape')dialog.events.cancel({preventDefault(){}});
  if(action==='close')dialog.close();
  assert.equal(await promise,action==='accept');assert.equal(dialog.removed,true);
 }
 console.log('Subscription consent accept, decline, Escape, and close passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
