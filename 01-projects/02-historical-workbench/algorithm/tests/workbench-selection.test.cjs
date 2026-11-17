const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const source=fs.readFileSync(process.env.CHANLUN_UI_TEST_FILE||require('node:path').join(__dirname,'../workbench/web/app.js'),'utf8');
function makeElement(){return {hidden:false,textContent:'',children:[],dataset:{},classList:{toggle(){}},append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items;this.textContent=items.map(x=>x.textContent||'').join(' ')}};}
function setup(api){
 const elements=new Map();const el=selector=>{if(!elements.has(selector))elements.set(selector,makeElement());return elements.get(selector)};
 const S={selected:'bj920000',job:'jobB',charts:[],stockRequest:0,marketRequest:0,q:'',exchange:'',filter:'',offset:0,limit:40,data:{available:true,summary:{symbol:'bj920000'}},detailJob:'jobA'};
 const context={S,api,URLSearchParams,document:{},window:{},$:el,$$:selector=>selector==='#market-body tr'?el('#market-body').children:[],
  node:(tag,cls,text)=>({...makeElement(),textContent:text||'',className:cls||''}),button:(text,action)=>({...makeElement(),textContent:text,onclick:action}),
  text:(selector,value)=>el(selector).textContent=value,integer:String,fmt:x=>String(x??'—'),toast:()=>{},openJob:()=>{},view:()=>{},renderStock:()=>{context.rendered=S.data.summary.symbol;}};
 vm.createContext(context);
 const a=source.indexOf('async function refreshMarket('),b=source.indexOf('\nfunction renderStock(){',a);
 vm.runInContext(source.slice(a,b),context);
 return {context,S,el};
}
const row=(symbol,state='success')=>({symbol,code:symbol.slice(2),name:symbol,exchange:symbol.slice(0,2),item_state:state,mode:state==='success'?'full':null});
test('task switch selects its successful stock instead of stale previous stock',async()=>{
 const x=setup(async path=>path.startsWith('/api/stocks')?{rows:[row('sz002149')],total:1}:{available:true,summary:{symbol:'sz002149'}});
 await x.context.refreshMarket({selectFirst:true});assert.equal(x.S.selected,'sz002149');assert.equal(x.context.rendered,'sz002149');assert.equal(x.S.detailJob,'jobB');
});
test('first successful result wins over pending or failed rows',async()=>{
 const x=setup(async path=>path.startsWith('/api/stocks')?{rows:[row('sh600001','failed'),row('sz002149')],total:2}:{available:true,summary:{symbol:'sz002149'}});
 await x.context.refreshMarket({selectFirst:true});assert.equal(x.S.selected,'sz002149');
});
test('empty task filter clears stale chart and selected symbol',async()=>{
 const x=setup(async()=>({rows:[],total:0}));await x.context.refreshMarket({selectFirst:true});
 assert.equal(x.S.selected,'');assert.equal(x.S.data,null);assert.equal(x.el('#stock-detail').hidden,true);
});
test('details show loading and old data is cleared immediately',async()=>{
 let release;const pending=new Promise(resolve=>release=resolve);const x=setup(()=>pending);
 const request=x.context.selectStock('sz002149');assert.equal(x.S.data,null);assert.equal(x.el('#stock-detail').hidden,true);assert.ok(x.el('#stock-empty').textContent.includes('正在加载'));
 release({available:true,summary:{symbol:'sz002149'}});await request;assert.equal(x.context.rendered,'sz002149');
});
test('slow previous request never overwrites a newer selection',async()=>{
 const pending=new Map();const x=setup(path=>new Promise(resolve=>pending.set(path,resolve)));
 const first=x.context.selectStock('sh600001'),second=x.context.selectStock('sz002149');
 pending.get('/api/stock/sz002149?job=jobB')({available:true,summary:{symbol:'sz002149'}});await second;
 pending.get('/api/stock/sh600001?job=jobB')({available:true,summary:{symbol:'sh600001'}});await first;
 assert.equal(x.S.selected,'sz002149');assert.equal(x.context.rendered,'sz002149');
});
test('periodic list refresh does not restart an in-flight same-stock detail request',async()=>{
 let release,calls=0;const pending=new Promise(resolve=>release=resolve);
 const x=setup(path=>{if(path.startsWith('/api/stocks'))return Promise.resolve({rows:[row('sz002149')],total:1});calls++;return pending});
 const detail=x.context.selectStock('sz002149');await x.context.refreshMarket();assert.equal(calls,1);
 release({available:true,summary:{symbol:'sz002149'}});await detail;assert.equal(x.S.stockLoading,false);
});
