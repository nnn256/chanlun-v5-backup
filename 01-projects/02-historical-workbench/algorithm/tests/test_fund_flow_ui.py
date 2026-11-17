"""Fund-flow status, fresh retries and cancelled selection are browser contracts."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

NODE_TESTS=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const source=fs.readFileSync(process.argv[1],'utf8');
function element(tag){return {tag,children:[],textContent:'',className:'',disabled:false,append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},setAttribute(){}};}
const research={version:'v1.1',latest:{state:'neutral',features:{}},runtime:{closed_bars:1427,new_closed_bars:0},config_sha256:'abc'};
const good={state:'ready',status_code:'ready',exchange:'bj',exchange_name:'北交所',source:'Eastmoney daily fund-flow estimate',latest:{date:'2026-11-13',main_net_flow:-123456.78},rows_count:100,received_at:'2026-11-15T12:00:00+08:00'};
function setup(handler,symbol='bj920000'){
 const holder=element('holder'),nodes=[],timers=new Map(),calls=[];let serial=0;
 const ctx={window:{},AbortController,setTimeout:(fn,delay)=>{timers.set(++serial,{fn,delay});return serial},clearTimeout:id=>timers.delete(id),
 document:{createElement:tag=>{const n=element(tag);nodes.push(n);return n}},fetch:async(path,options)=>{calls.push({path,options});return handler?handler(path,options):{ok:true,json:async()=>good}}};
 vm.createContext(ctx);vm.runInContext(source,ctx);ctx.window.RegimeResearch.render(holder,research,symbol);
 return {ctx,holder,nodes,timers,calls,api:ctx.window.RegimeResearch,button:()=>nodes.find(n=>n.tag==='button'),output:()=>nodes.find(n=>n.className==='regime-flow')};
}
const reply=data=>({ok:true,status:200,json:async()=>data});
const flush=()=>new Promise(r=>setImmediate(r));
test('BSE successful response displays provider, exchange and actual main-flow estimate',async()=>{
 const x=setup();await x.button().onclick();const text=x.output().textContent;
 assert.ok(text.includes('北交所'));assert.ok(text.includes(good.source));assert.ok(text.includes('-123456.78 元'));assert.ok(text.includes('2026-11-13'));
 assert.ok(text.includes('未验证历史发布时间'));assert.equal(x.button().textContent,'刷新资金流证据');assert.equal(x.timers.size,0);assert.equal(x.button().disabled,false);
});
test('upstream disconnect is a retriable request error rather than exchange unsupported',async()=>{
 const x=setup(()=>reply({state:'unavailable',status_code:'upstream_error',exchange:'bj',source:'Eastmoney',reason:'RemoteDisconnected',error_detail:'连接已断开'}));
 await x.button().onclick();const text=x.output().textContent;assert.ok(text.includes('上游资金流请求失败'));assert.ok(text.includes('RemoteDisconnected'));assert.ok(text.includes('连接已断开'));assert.ok(!text.includes('不支持'));assert.ok(!text.includes('主力净流估计 0'));assert.equal(x.button().textContent,'重试资金流（重新获取）');
});
test('legacy unsupported exchange reason remains explicit and distinct',async()=>{
 const x=setup(()=>reply({state:'unavailable',reason:'未验证北交所个股资金流接口'}));await x.button().onclick();
 assert.ok(x.output().textContent.includes('当前接口不支持或尚未验证此交易所'));assert.ok(x.output().textContent.includes('未验证北交所个股资金流接口'));
});
test('no records does not masquerade as a network failure',async()=>{
 const x=setup(()=>reply({state:'unavailable',status_code:'no_records',reason:'供应商返回空记录',source:'Eastmoney',exchange_name:'北交所'}));await x.button().onclick();
 assert.ok(x.output().textContent.includes('供应商暂无资金流记录'));assert.ok(!x.output().textContent.includes('上游资金流请求失败'));
});
test('data validation errors retain the real reason without manufacturing zeros',async()=>{
 const x=setup(()=>reply({state:'unavailable',status_code:'validation_error',reason:'资金流来源证券身份不一致'}));await x.button().onclick();assert.ok(x.output().textContent.includes('资金流数据校验失败'));assert.ok(x.output().textContent.includes('证券身份不一致'));
});
test('first read can use cache but explicit retry bypasses failure cache with fresh=1',async()=>{
 const x=setup(()=>reply({state:'unavailable',status_code:'upstream_error',reason:'temporary'}));await x.button().onclick();await x.button().onclick();
 assert.equal(x.calls[0].path,'/api/research-context/bj920000');assert.equal(x.calls[1].path,'/api/research-context/bj920000?fresh=1');
 assert.ok(x.calls.every(c=>c.options.signal instanceof AbortSignal));
});
test('refreshing successful flow evidence also explicitly requests a fresh observation',async()=>{
 const x=setup();await x.button().onclick();await x.button().onclick();assert.ok(x.calls[1].path.endsWith('?fresh=1'));
});
test('pending button is single flight',async()=>{
 let resolve;const x=setup(()=>new Promise(r=>resolve=r)),first=x.button().onclick();await x.button().onclick();
 assert.equal(x.calls.length,1);assert.equal(x.button().disabled,true);resolve(reply(good));await first;
});
test('30 second wait aborts the fetch, shows timeout and enables explicit retry',async()=>{
 const x=setup((path,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})),{once:true})));
 const work=x.button().onclick();assert.equal([...x.timers.values()][0].delay,30000);for(const timer of [...x.timers.values()])timer.fn();await work;
 assert.equal(x.calls[0].options.signal.aborted,true);assert.ok(x.output().textContent.includes('超过30秒'));assert.equal(x.button().disabled,false);assert.equal(x.timers.size,0);
});
test('late success from an abort-ignoring provider cannot replace the timeout result',async()=>{
 let resolve;const x=setup(()=>new Promise(r=>resolve=r)),work=x.button().onclick();for(const timer of [...x.timers.values()])timer.fn();resolve(reply(good));await work;
 assert.ok(x.output().textContent.includes('超过30秒'));assert.ok(!x.output().textContent.includes('主力净流估计'));
});
test('changing stock invalidates and aborts old request without writing new stock output',async()=>{
 let resolve;const x=setup(()=>new Promise(r=>resolve=r)),button=x.button(),old=x.output(),work=button.onclick();x.api.invalidate(x.holder);x.api.render(x.holder,research,'sh600000');
 const latest=x.nodes.filter(n=>n.className==='regime-flow').at(-1);assert.equal(x.calls[0].options.signal.aborted,true);assert.equal(x.timers.size,0);
 resolve(reply(good));await work;assert.equal(latest.textContent,'');assert.ok(old.textContent.includes('正在获取'));assert.equal(x.holder._regimeContext.symbol,'sh600000');
});
test('unchanged research runtime does not clear fetched flow evidence',async()=>{
 const x=setup();await x.button().onclick();const before=x.output().textContent,button=x.button();
 assert.equal(x.api.updateRuntime(x.holder,{...research,runtime:{closed_bars:1427,new_closed_bars:0,session_reused:true}},'bj920000'),true);
 assert.equal(x.output().textContent,before);assert.equal(x.button(),button);assert.equal(x.button().textContent,'刷新资金流证据');
});
test('HTTP error body uses source and precise reason with a retry control',async()=>{
 const x=setup(()=>({ok:false,status:503,json:async()=>({source:'Eastmoney',reason:'Service temporarily unavailable'})}));await x.button().onclick();
 assert.ok(x.output().textContent.includes('上游资金流请求失败'));assert.ok(x.output().textContent.includes('Service temporarily unavailable'));assert.ok(x.output().textContent.includes('Eastmoney'));assert.equal(x.button().disabled,false);
});
test('malformed JSON and fetch failures are visible without unsupported-exchange claims',async()=>{
 for(const error of [new SyntaxError('invalid response JSON'),new Error('connection failed')]){
  const x=setup(()=>Promise.reject(error));await x.button().onclick();assert.ok(x.output().textContent.includes(error.message));assert.ok(x.output().textContent.includes('北交所'));assert.ok(x.output().textContent.includes('来源'));assert.ok(!x.output().textContent.includes('不支持'));
 }
});
test('malformed success payload cannot be rendered as a zero-flow observation',async()=>{
 for(const value of [undefined,null,'',false,'not-a-number']){
  const x=setup(()=>reply({...good,latest:{date:'2026-11-13',main_net_flow:value}}));await x.button().onclick();assert.ok(x.output().textContent.includes('资金流数据校验失败'));assert.ok(!x.output().textContent.includes('主力净流估计 0'));assert.equal(x.button().textContent,'重试资金流（重新获取）');
 }
});
test('real zero is displayed as a measured vendor estimate, not missing',async()=>{
 const x=setup(()=>reply({...good,latest:{date:'2026-11-13',main_net_flow:0},cache_age_seconds:12.2}));await x.button().onclick();assert.ok(x.output().textContent.includes('主力净流估计 0.00 元'));assert.ok(x.output().textContent.includes('缓存 12.2 秒'));
});
'''


class FundFlowUIContractTests(unittest.TestCase):
    def test_states_refresh_and_cancelled_stock(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node.js is required')
        result=subprocess.run([node,'-e',NODE_TESTS,str(ROOT/'workbench/web/regime-research.js')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('tests 16',result.stdout)


if __name__=='__main__':unittest.main()
