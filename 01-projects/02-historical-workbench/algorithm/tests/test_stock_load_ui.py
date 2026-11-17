"""Run real selection functions against pending/aborted browser requests."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

NODE_TESTS = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const source=fs.readFileSync(process.argv[1],'utf8');
function element(){return {hidden:false,checked:false,textContent:'',children:[],dataset:{},classList:{toggle(){},remove(){}},append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items;this.textContent=items.map(x=>x.textContent||'').join(' ')}};}
function setup(handler){
 const elements=new Map(),timeouts=new Map(),intervals=new Map(),calls=[],renders=[];let timer=0,now=0;
 const el=selector=>{if(!elements.has(selector))elements.set(selector,element());return elements.get(selector)};
 const S={selected:'bj920000',job:'',period:'all',view:'market',charts:[],stockRequest:0,marketRequest:0,q:'',exchange:'',filter:'',offset:0,limit:40,data:null,detailJob:null,marketRows:[{symbol:'bj920000',name:'安徽凤凰'}]};
 const context={S,AbortController,URLSearchParams,document:{hidden:false},window:{},Date:{now:()=>now},$:el,$$:selector=>selector==='#market-body tr'?el('#market-body').children:[],
  node:(tag,cls,text)=>({...element(),textContent:text||'',className:cls||''}),button:(text,action)=>({...element(),textContent:text,onclick:action}),
  text:(selector,value)=>el(selector).textContent=value,integer:String,fmt:x=>String(x??'—'),toast:()=>{},openJob:()=>{},view:()=>{},
  prepareSignalDisplay:()=>{},renderStock:(preserve=false,keepPeriod=false)=>{if(!keepPeriod&&S.period!=='all'&&!S.data.chart.panels.some(panel=>panel.period===S.period))S.period='all';renders.push(S.data)},renderLiveStatus:()=>{},renderCharts:()=>{},renderKlineSummary:()=>{},
  setTimeout:(fn,ms)=>{timeouts.set(++timer,{fn,ms});return timer},clearTimeout:id=>timeouts.delete(id),
  setInterval:(fn,ms)=>{intervals.set(++timer,{fn,ms});return timer},clearInterval:id=>intervals.delete(id)};
 context.api=(path,body,options)=>{calls.push({path,options});return handler(path,options)};
 vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('async function refreshMarket('),source.indexOf('\nfunction renderStock(',source.indexOf('async function refreshMarket('))),context);
 vm.runInContext(source.slice(source.indexOf('function liveSnapshotToken('),source.indexOf("\n$('#refresh-now')",source.indexOf('async function quoteTick('))),context);
 vm.runInContext(source.slice(source.indexOf('async function selectPeriod('),source.indexOf('\nfunction setRange(',source.indexOf('async function selectPeriod('))),context);
 return {context,S,el,calls,renders,timeouts,intervals,advance:ms=>{now+=ms;for(const item of intervals.values())item.fn()}};
}
function deferred(options,ignoreAbort=false){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});if(!ignoreAbort)options?.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})),{once:true});return {promise,resolve,reject};}
const saved=(symbol='bj920000')=>({available:true,summary:{symbol,last_close_time:'2026-11-12T15:00:00+08:00'},chart:{panels:[{period:'day'}]}});
const live=(symbol='bj920000')=>({...saved(symbol),summary:{...saved(symbol).summary,live:{received_at:'2026-11-15T10:00:00+08:00'}},chart:{panels:[{period:'day'},{period:'30m'},{period:'5m'}]}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('live selection shows dated saved snapshot before live all resolves',async()=>{
 let pending;const historical=saved();const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending=deferred(options)).promise:Promise.resolve(historical));x.el('#live-quote').checked=true;
 const operation=x.context.selectStock('bj920000');await flush();
 assert.equal(x.renders.length,1);assert.equal(x.S.data,historical);assert.equal(x.S.data.summary.live,undefined);assert.ok(x.el('#live-quote-status').textContent.includes('历史快照'));assert.equal(x.S.stockLoading,true);
 await x.context.quoteTick();assert.equal(x.calls.length,2);assert.equal(x.calls[1].path,'/api/live-stock/bj920000?period=all');
 pending.resolve(live());await operation;assert.equal(x.renders.length,2);assert.ok(x.S.data.summary.live);assert.equal(x.S.stockLoading,false);assert.equal(x.timeouts.size+x.intervals.size,0);
});
test('failed live update retains saved snapshot and does not auto loop',async()=>{
 const historical=saved();let pending;const x=setup((path,options)=>path.startsWith('/api/stocks?')?Promise.resolve({rows:[{symbol:'bj920000',code:'920000',name:'安徽凤凰',exchange:'bj',item_state:'success'}],total:1}):path.startsWith('/api/live-stock/')?(pending=deferred(options)).promise:Promise.resolve(historical));x.el('#live-quote').checked=true;
 const operation=x.context.selectStock('bj920000');await flush();pending.reject(new Error('upstream timeout'));await operation;
 assert.equal(x.S.data,historical);assert.equal(x.el('#stock-detail').hidden,false);assert.ok(x.el('#live-quote-status').textContent.includes('实时尚未更新'));assert.ok(x.el('#live-quote-status').children.some(item=>item.textContent==='重试实时更新'));
 const requests=x.calls.length;await x.context.quoteTick();await x.context.refreshMarket();assert.equal(x.calls.length,requests+1);assert.equal(x.renders.length,1);
});
test('switching stock aborts the older fetch and ignores a late answer',async()=>{
 const pending=[];const x=setup((path,options)=>{const p=deferred(options,true);pending.push(p);return p.promise});
 const first=x.context.selectStock('bj920000'),second=x.context.selectStock('sz000001');assert.equal(x.calls[0].options.signal.aborted,true);
 pending[1].resolve(saved('sz000001'));await second;pending[0].resolve(saved('bj920000'));await first;
 assert.equal(x.renders.length,1);assert.equal(x.S.data.summary.symbol,'sz000001');assert.equal(x.S.stockLoading,false);
});
test('same stock mode change supersedes pending live snapshot request',async()=>{
 const pending=[];const x=setup((path,options)=>{const p=deferred(options);pending.push(p);return p.promise});x.el('#live-quote').checked=true;
 const first=x.context.selectStock('bj920000');x.el('#live-quote').checked=false;const second=x.context.selectStock('bj920000');
 assert.equal(x.calls.length,2);assert.equal(x.calls[0].options.signal.aborted,true);pending[1].resolve(saved());await second;await first;
 assert.equal(x.renders.length,1);assert.equal(x.S.data.summary.live,undefined);
});
test('duplicate same selection is single flight but changing period is allowed',async()=>{
 const pending=[];const x=setup((path,options)=>{const p=deferred(options);pending.push(p);return p.promise});x.el('#live-quote').checked=true;
 const first=x.context.selectStock('bj920000');await x.context.selectStock('bj920000');assert.equal(x.calls.length,1);
 x.S.period='day';const second=x.context.selectStock('bj920000');assert.equal(x.calls.length,2);assert.equal(x.calls[0].options.signal.aborted,true);
 pending[1].resolve({available:false});await flush();assert.equal(x.calls[2].path,'/api/local-stock/bj920000?period=day');pending[2].resolve({available:false,state:'unavailable'});await flush();assert.equal(x.calls[3].path,'/api/live-stock/bj920000?period=day');pending[3].resolve(live());await second;await first;
});
test('timeout preserves snapshot and removes the loading lock',async()=>{
 let pending;const historical=saved();const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending=deferred(options)).promise:Promise.resolve(historical));x.el('#live-quote').checked=true;
 const operation=x.context.selectStock('bj920000');await flush();for(const timer of [...x.timeouts.values()])timer.fn();await operation;
 assert.equal(x.S.data,historical);assert.equal(x.S.stockLoading,false);assert.ok(x.el('#live-quote-status').textContent.includes('60秒'));assert.equal(x.timeouts.size+x.intervals.size,0);
});
test('no saved snapshot waits for live with truthful loading state',async()=>{
 let pending;const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending=deferred(options)).promise:Promise.resolve({available:false}));x.el('#live-quote').checked=true;
 const operation=x.context.selectStock('bj920000');await flush();assert.equal(x.renders.length,0);assert.ok(x.el('#stock-empty').textContent.includes('没有可立即展示的已保存结果'));
 x.advance(4000);assert.ok(x.el('#stock-empty').textContent.includes('已等待 4 秒'));pending.resolve(live());await operation;assert.equal(x.renders.length,1);
});
test('historical task never fetches live and passes an abort signal',async()=>{
 const x=setup(()=>Promise.resolve(saved()));x.S.job='job-1';x.el('#live-quote').checked=true;await x.context.selectStock('bj920000');
 assert.equal(x.calls.length,1);assert.equal(x.calls[0].path,'/api/stock/bj920000?job=job-1');assert.ok(x.calls[0].options.signal);assert.equal(x.el('#live-quote').checked,false);
});
test('api forwards selection abort signal without changing request data',async()=>{
 const controller=new AbortController();let called;const context={fetch:async(path,options)=>{called={path,options};return {ok:true,json:async()=>({available:true})}}};vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('\nfunction button(',source.indexOf('async function api('))),context);
 await context.api('/api/stock/bj920000',undefined,{signal:controller.signal});assert.equal(called.options.signal,controller.signal);
 await context.api('/api/jobs',{scope:'all'});assert.equal(called.options.method,'POST');assert.equal(called.options.body,'{"scope":"all"}');
});
for(const order of ['late-live-first','late-live-last'])test('pending live to saved week is isolated: '+order,async()=>{
 let livePending,weekPending;const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(livePending=deferred(options,true)).promise:path.includes('?period=week')?(weekPending=deferred(options)).promise:Promise.resolve(saved()));x.el('#live-quote').checked=true;
 const initial=x.context.selectStock('bj920000');await flush();const extended=x.context.selectPeriod('week');await flush();
 assert.equal(x.el('#live-quote').checked,false);assert.equal(x.calls.find(call=>call.path.startsWith('/api/live-stock/')).options.signal.aborted,true);assert.ok(weekPending);
 if(order==='late-live-first'){livePending.resolve(live());await initial;assert.equal(x.S.data.summary.live,undefined);}
 weekPending.resolve({available:true,panel:{period:'week'}});await extended;assert.equal(x.S.period,'week');assert.equal(x.S.data.summary.live,undefined);assert.ok(x.S.data.chart.panels.some(panel=>panel.period==='week'));
 if(order==='late-live-last'){livePending.resolve(live());await initial;assert.equal(x.S.period,'week');assert.equal(x.S.data.summary.live,undefined);}
});
test('saved week and month responses follow the last actual period click',async()=>{
 const pending=new Map();const x=setup((path,options)=>{const p=deferred(options,true);pending.set(path,p);return p.promise});x.S.data=saved();
 const week=x.context.selectPeriod('week'),month=x.context.selectPeriod('month');assert.equal(x.calls[0].options.signal.aborted,true);
 pending.get('/api/stock/bj920000?period=month').resolve({available:true,panel:{period:'month'}});await month;
 pending.get('/api/stock/bj920000?period=week').resolve({available:true,panel:{period:'week'}});await week;
 assert.equal(x.S.period,'month');assert.equal(x.S.data.chart.panels.some(panel=>panel.period==='week'),false);
});
test('native period click during staged live replaces pending all request',async()=>{
 const pending=[];const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending.push(deferred(options)),pending.at(-1).promise):Promise.resolve(saved()));x.el('#live-quote').checked=true;
 const first=x.context.selectStock('bj920000');await flush();const day=x.context.selectPeriod('day');await flush();assert.equal(x.calls.filter(call=>call.path.startsWith('/api/live-stock/')).length,2);assert.equal(x.calls.at(-1).path,'/api/live-stock/bj920000?period=day');
 pending[1].resolve(live());await day;await first;assert.equal(x.S.period,'day');assert.ok(x.S.data.summary.live);
});
test('snapshot missing requested minute period does not reset the user selection',async()=>{
 let pending;const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending=deferred(options)).promise:Promise.resolve(saved()));x.el('#live-quote').checked=true;x.S.period='5m';
 const operation=x.context.selectStock('bj920000');await flush();assert.equal(x.S.period,'5m');assert.ok(x.el('#live-quote-status').textContent.includes('保存结果不含所选周期'));assert.equal(x.calls.at(-1).path,'/api/live-stock/bj920000?period=5m');
 pending.resolve(live());await operation;assert.equal(x.S.period,'5m');
});
test('late saved period reply cannot append to a newly loaded live bundle',async()=>{
 let weekPending,livePending;const x=setup((path,options)=>path.includes('?period=week')?(weekPending=deferred(options,true)).promise:path.startsWith('/api/live-stock/')?(livePending=deferred(options)).promise:Promise.resolve(saved()));x.S.data=saved();
 const week=x.context.selectPeriod('week');x.el('#live-quote').checked=true;const realtime=x.context.selectStock('bj920000');await flush();livePending.resolve(live());await realtime;
 weekPending.resolve({available:true,panel:{period:'week'}});await week;assert.ok(x.S.data.summary.live);assert.equal(x.S.data.chart.panels.some(panel=>panel.period==='week'),false);
});
test('live retry waits 60 seconds, stays single flight, then resumes normal polling',async()=>{
 const pending=[];const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending.push(deferred(options)),pending.at(-1).promise):Promise.resolve(saved()));x.el('#live-quote').checked=true;
 const initial=x.context.selectStock('bj920000');await flush();pending[0].reject(new Error('upstream timeout'));await initial;assert.equal(x.S.stockRetryAt,60000);
 x.advance(59000);await x.context.quoteTick();assert.equal(pending.length,1);
 x.advance(1000);const retry=x.context.quoteTick();await x.context.quoteTick();assert.equal(pending.length,2);assert.equal(x.S.quotePending,true);
 pending[1].resolve(live());await retry;assert.equal(x.S.stockFailedKey,null);assert.equal(x.S.stockRetryAt,null);
 x.advance(15000);const normal=x.context.quoteTick();assert.equal(pending.length,3);pending[2].resolve(live());await normal;assert.ok(x.S.data.summary.live);
});
test('failed automatic live retry starts a new 60-second backoff',async()=>{
 const pending=[];const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending.push(deferred(options)),pending.at(-1).promise):Promise.resolve(saved()));x.el('#live-quote').checked=true;
 const initial=x.context.selectStock('bj920000');await flush();pending[0].reject(new Error('offline'));await initial;
 x.advance(60000);const retry=x.context.quoteTick();pending[1].reject(new Error('still offline'));await retry;assert.equal(x.S.stockRetryAt,120000);assert.ok(x.S.data.available);
 x.advance(59000);await x.context.quoteTick();assert.equal(pending.length,2);x.advance(1000);const next=x.context.quoteTick();assert.equal(pending.length,3);pending[2].resolve(live());await next;
});
test('automatic recovery without a visible snapshot uses the full selection flow',async()=>{
 let reads=0;const pending=[];const x=setup((path,options)=>path.startsWith('/api/live-stock/')?(pending.push(deferred(options)),pending.at(-1).promise):path.startsWith('/api/local-stock/')?Promise.resolve({available:false,state:'unavailable',reason:'no cached history'}):Promise.resolve(++reads===1?{available:false}:saved()));x.el('#live-quote').checked=true;
 const initial=x.context.selectStock('bj920000');await flush();pending[0].reject(new Error('offline'));await initial;assert.equal(x.S.data,null);assert.equal(x.el('#stock-detail').hidden,true);
 x.advance(60000);const retry=x.context.quoteTick();await flush();assert.equal(reads,2);assert.equal(pending.length,2);assert.equal(x.el('#stock-detail').hidden,false);assert.equal(x.el('#stock-empty').hidden,true);assert.equal(x.S.stockLoading,true);
 await x.context.quoteTick();assert.equal(pending.length,2);pending[1].resolve(live());await retry;assert.ok(x.S.data.summary.live);assert.equal(x.S.stockRetryAt,null);
});
test('saved-only failure never creates an automatic live retry',async()=>{
 const x=setup(path=>path.startsWith('/api/stocks?')?Promise.resolve({rows:[{symbol:'bj920000',code:'920000',name:'安徽凤凰',exchange:'bj',item_state:'success'}],total:1}):Promise.reject(new Error('missing saved file')));await x.context.selectStock('bj920000');assert.equal(x.S.stockRetryAt,null);
 x.advance(120000);await x.context.quoteTick();await x.context.refreshMarket();assert.equal(x.calls.length,3);assert.equal(x.calls.some(call=>call.path.startsWith('/api/live-stock/')),false);
});
test('switching stock and live mode clears retry state from the old selection',async()=>{
 const x=setup(path=>path.startsWith('/api/live-stock/')?Promise.reject(new Error('offline')):Promise.resolve(saved(path.includes('sz000001')?'sz000001':'bj920000')));x.el('#live-quote').checked=true;await x.context.selectStock('bj920000');assert.equal(x.S.stockRetryAt,60000);
 x.el('#live-quote').checked=false;await x.context.selectStock('sz000001');assert.equal(x.S.stockFailedKey,null);assert.equal(x.S.stockRetryAt,null);const count=x.calls.length;x.advance(120000);await x.context.quoteTick();assert.equal(x.calls.length,count);assert.equal(x.S.data.summary.symbol,'sz000001');
});
test('partial live reply preserves the requested missing period instead of changing to all',async()=>{
 const partial=live();partial.chart.panels=[{period:'day'}];partial.summary.live.period_errors={'5m':'upstream unavailable'};
 const x=setup(path=>Promise.resolve(path.startsWith('/api/live-stock/')?partial:saved()));x.el('#live-quote').checked=true;x.S.period='5m';await x.context.selectStock('bj920000');
 assert.equal(x.S.period,'5m');assert.equal(x.S.data.summary.live.period_errors['5m'],'upstream unavailable');await x.context.quoteTick();assert.equal(x.S.period,'5m');
});
'''


class StockLoadUiBehaviorTests(unittest.TestCase):
    def test_selection_lifecycle_with_real_frontend_functions(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js required for frontend behavior checks')
        result = subprocess.run([node, '-e', NODE_TESTS, str(ROOT / 'workbench/web/app.js')],
                                cwd=ROOT, capture_output=True, text=True,
                                encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('tests 21', result.stdout)


if __name__ == '__main__':
    unittest.main()
