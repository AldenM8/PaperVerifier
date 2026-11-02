const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
class Element {
 constructor(){this.children=[];this.events={};this.style={};this.className='';this.value='';this.classList={contains:n=>this.className.split(' ').includes(n),add:n=>{if(!this.classList.contains(n))this.className+=' '+n},remove:n=>{this.className=this.className.split(' ').filter(x=>x!==n).join(' ')}}}
 append(...nodes){this.children.push(...nodes)} replaceChildren(){this.children=[]} setAttribute(){} addEventListener(n,f){this.events[n]=f} setPointerCapture(){} focus(){} closest(){return null}
}
const list=new Element(),messages=[],listeners={};const parent={postMessage:v=>messages.push(v)};
const context={parent,document:{getElementById:()=>list,createElement:()=>new Element(),body:new Element(),documentElement:{scrollHeight:300}},window:{addEventListener:(n,f)=>listeners[n]=f},ResizeObserver:class {observe(){}},console};
const html=fs.readFileSync(path.join(__dirname,'../swipe_component/index.html'),'utf8');
vm.runInNewContext(html.split('<script>')[1].split('</script>')[0],context);
function render(){listeners.message({source:parent,data:{type:'streamlit:render',args:{revision:'version-1',rows:[{title:'Test paper',authors:'Alex Chen',year:'2020'}]}}})}
render();let row=list.children[0],front=row.children[1],del=row.children[0];
const event=(x,y)=>({clientX:x,clientY:y,pointerId:1,target:front});
front.events.pointerdown(event(10,10));front.events.pointermove(event(82,12));front.events.pointerup(event(82,12));
assert(row.classList.contains('open'));assert.equal(front.style.transform,'translateX(86px)');
assert.equal(messages.filter(x=>x.type==='streamlit:setComponentValue').length,0,'Swipe alone must not delete');
del.onclick();let value=messages.find(x=>x.type==='streamlit:setComponentValue').value;
assert.equal(value.action,'delete');assert.equal(value.index,0);assert.equal(value.revision,'version-1');
render();row=list.children[0];front=row.children[1];
front.events.pointerdown(event(10,10));front.events.pointermove(event(12,80));front.events.pointerup(event(12,80));
assert(!row.classList.contains('open'),'Vertical scrolling must not reveal delete');
console.log('Swipe reveal, explicit delete, and vertical scrolling checks passed');
