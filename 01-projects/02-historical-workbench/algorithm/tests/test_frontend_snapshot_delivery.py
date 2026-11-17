"""Exercise conditional live delivery and retained research UI with real functions."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

NODE_TESTS=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const source=fs.readFileSync(process.argv[1],'utf8'),researchSource=fs.readFileSync(process.argv[2],'utf8');
const slice=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const clone=value=>JSON.parse(JSON.stringify(value));
const ID='a'.repeat(64),SHA='b'.repeat(64);
function element(){return {children:[],textContent:'',disabled:false,checked:false,hidden:false,classList:{add(){},remove(){},toggle(){}},append(...a){this.children.push(...a)},replaceChildren(...a){this.children=a}};}
function previous(){return {available:true,snapshot_id:ID,summary:{symbol:'bj920000',live:{received_at:'old'}},chart:{symbol:'bj920000',input_sha256:{day:'input'},panels:[{period:'day',presentation_sha256:SHA,bars:[{close:10}],all_signals:[{id:'proof'}],live_session:{total_closed:1},regime_research:{latest:{state:'neutral',features:{}},runtime:{new_closed_bars:1427,closed_bars:1427},provenance:{open_bar_excluded:false},config_sha256:'config'}}]}};}
function unchanged(){return {available:true,unchanged:true,snapshot_id:ID,summary:{symbol:'bj920000',live:{received_at:'new'}},chart_metadata:{symbol:'bj920000',as_of:'now',input_sha256:{day:'input'}},panel_updates:[{period:'day',presentation_sha256:SHA,received_at:'new',source_receipt:{hash:'new'},live_session:{total_closed:1},research_runtime:{new_closed_bars:0,closed_bars:1427,session_reused:true},research_provenance:{open_bar_excluded:false}}]};}
function setup(handler){
 const elements=new Map(),el=s=>{if(!elements.has(s))elements.set(s,element());return elements.get(s)},renders=[],calls=[];
 const S={selected:'bj920000',stockRequest:1,job:'',period:'day',view:'market',data:previous(),charts:[]};el('#live-quote').checked=true;
 const ctx={S,$:el,$$:()=>[],window:{},document:{hidden:false},Date,AbortController,URLSearchParams,console,
   setTimeout:()=>1,clearTimeout(){},node:(tag,cls,text)=>Object.assign(element(),{textContent:text||'',className:cls}),button:()=>element(),
   renderStock:()=>renders.push(S.data),renderLiveStatus(){},selectStock:async()=>{throw Error('unexpected select')},
   api:async(path,body,options)=>{calls.push({path,options});return handler?handler(path,options):unchanged()}};
 vm.createContext(ctx);vm.runInContext(slice('function liveSnapshotToken(',"\n$('#refresh-now')"),ctx);
 return {ctx,S,el,renders,calls};
}
test('unchanged envelope retains all static candle and signal objects with fresh metadata',()=>{
 const x=setup(),old=x.S.data,panel=old.chart.panels[0],next=x.ctx.mergeLiveSnapshot(old,unchanged());
 assert.equal(next.chart.panels[0].bars,panel.bars);assert.equal(next.chart.panels[0].all_signals,panel.all_signals);
 assert.equal(next.chart.panels[0].received_at,'new');assert.equal(next.summary.live.received_at,'new');
 assert.equal(next.chart.panels[0].regime_research.runtime.new_closed_bars,0);assert.equal(old.chart.panels[0].regime_research.runtime.new_closed_bars,1427);
 assert.equal(next.chart.as_of,'now');assert.equal(next.unchanged,undefined);
});
for(const [name,mutate] of [
 ['snapshot',u=>u.snapshot_id='c'.repeat(64)],['stock',u=>u.summary.symbol='sz000001'],
 ['chartstock',u=>u.chart_metadata.symbol='sz000001'],['period',u=>u.panel_updates[0].period='5m'],
 ['signal identity',u=>u.panel_updates[0].presentation_sha256='c'.repeat(64)],['missing period',u=>u.panel_updates=[]],
 ['duplicate period',u=>u.panel_updates.push(u.panel_updates[0])],['closed input',u=>u.chart_metadata.input_sha256.day='changed'],
 ['nonlive',u=>delete u.summary.live]])test('refuses inconsistent unchanged envelope: '+name,()=>{
 const x=setup(),u=unchanged();mutate(u);assert.throws(()=>x.ctx.mergeLiveSnapshot(x.S.data,u),/身份已变化/);
});
test('normal full responses remain compatible and do not reuse old bars',()=>{
 const x=setup(),full=previous();delete full.snapshot_id;full.chart.panels[0].bars[0].close=99;
 assert.equal(x.ctx.mergeLiveSnapshot(x.S.data,full),full);assert.equal(x.ctx.liveSnapshotToken(full,'bj920000'),null);
});
test('fresh chart metadata replaces obsolete errors and ignores input mapping insertion order',()=>{
 const x=setup(),old=x.S.data,u=unchanged();old.chart.period_errors={old:'stale'};
 old.chart.input_sha256={day:'input','5m':'second'};u.chart_metadata.input_sha256={'5m':'second',day:'input'};
 const next=x.ctx.mergeLiveSnapshot(old,u);assert.equal(next.chart.period_errors,undefined);assert.equal(next.chart.panels[0].bars,old.chart.panels[0].bars);
});
test('quote sends known snapshot but still requests current upstream data on forced refresh',async()=>{
 const x=setup();await x.ctx.quoteTick(true);
 assert.equal(x.calls.length,1);assert.ok(x.calls[0].path.includes('fresh=1&known_snapshot='+ID));
 assert.equal(x.S.data.summary.live.received_at,'new');assert.equal(x.renders.length,1);assert.equal(x.S.quotePending,false);
});
test('mismatched delta makes one full retry and never exposes partial old data',async()=>{
 const full=previous();full.chart.panels[0].bars[0].close=42;
 const x=setup(path=>path.includes('known_snapshot=')?{...unchanged(),snapshot_id:'c'.repeat(64)}:full);
 await x.ctx.quoteTick(true);assert.equal(x.calls.length,2);assert.ok(!x.calls[1].path.includes('known_snapshot='));
 assert.equal(x.renders.length,1);assert.equal(x.S.data.chart.panels[0].bars[0].close,42);
});
test('repeated invalid delta retains last snapshot and enters failure backoff',async()=>{
 const x=setup(()=>({...unchanged(),snapshot_id:'c'.repeat(64)})),old=x.S.data;
 await x.ctx.quoteTick(true);assert.equal(x.calls.length,2);assert.equal(x.S.data,old);assert.equal(x.renders.length,0);assert.ok(x.S.stockRetryAt>Date.now());
});
test('switching selection before delta arrives does not apply or make a full retry',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const x=setup(()=>pending),old=x.S.data;
 const work=x.ctx.quoteTick(true);x.S.selected='sz000001';x.S.stockRequest++;resolve(unchanged());await work;
 assert.equal(x.calls.length,1);assert.equal(x.S.data,old);assert.equal(x.renders.length,0);
});
test('legacy server full response works without a known token',async()=>{
 const x=setup(()=>previous());delete x.S.data.snapshot_id;await x.ctx.quoteTick();
 assert.equal(x.calls.length,1);assert.ok(!x.calls[0].path.includes('known_snapshot='));assert.equal(x.renders.length,1);
});
function researchSetup(){
 const holder=element(),nodes=[];const ctx={window:{},AbortController,setTimeout,clearTimeout,document:{createElement:tag=>{const n=Object.assign(element(),{tag});nodes.push(n);return n}}};
 vm.createContext(ctx);vm.runInContext(researchSource,ctx);
 return {holder,ctx,nodes,api:ctx.window.RegimeResearch};
}
test('research runtime update preserves fetched flow evidence and button state',()=>{
 const x=researchSetup(),data=previous().chart.panels[0].regime_research;x.api.render(x.holder,data,'bj920000');
 const button=x.nodes.find(n=>n.tag==='button'),flow=x.nodes.find(n=>n.className==='regime-flow');flow.textContent='received fund-flow evidence';button.disabled=true;
 const children=x.holder.children.slice();assert.equal(x.api.updateRuntime(x.holder,{...data,runtime:{new_closed_bars:0,closed_bars:1427,session_reused:true}},'bj920000'),true);
 assert.deepEqual(x.holder.children,children);assert.equal(flow.textContent,'received fund-flow evidence');assert.equal(button.disabled,true);
 assert.ok(x.holder._regimeRuntime.textContent.includes('本次推进 0 根'));
});
test('fund flow completion from a prior stock is invalidated on selection change',async()=>{
 const x=researchSetup(),data=previous().chart.panels[0].regime_research;let resolve;
 x.ctx.fetch=()=>new Promise(r=>resolve=r);x.api.render(x.holder,data,'bj920000');const button=x.nodes.find(n=>n.tag==='button'),flow=x.nodes.find(n=>n.className==='regime-flow');
 const work=button.onclick();x.api.invalidate(x.holder);x.api.render(x.holder,data,'sz000001');
 resolve({ok:true,json:async()=>({state:'ready',latest:{date:'2026-11-13',main_net_flow:100},rows_count:1,received_at:'now'})});await work;
 assert.ok(flow.textContent.includes('正在获取供应商资金流…'));assert.equal(x.holder._regimeContext.symbol,'sz000001');
});
test('research identity reuses DOM only with a certified same stock presentation',()=>{
 const x=setup();x.ctx.window.RegimeResearch={};let renders=0,updates=0;
 x.ctx.RegimeResearch={render(){renders++},updateRuntime(){updates++;return true}};vm.runInContext(slice('function renderStockResearch(', '\nfunction renderStock('),x.ctx);
 x.ctx.renderStockResearch(x.S.data);x.ctx.renderStockResearch(x.S.data);assert.equal(renders,1);assert.equal(updates,1);
 x.S.data.chart.panels[0].presentation_sha256='c'.repeat(64);x.ctx.renderStockResearch(x.S.data);assert.equal(renders,2);
 delete x.S.data.chart.panels[0].presentation_sha256;x.ctx.renderStockResearch(x.S.data);x.ctx.renderStockResearch(x.S.data);assert.equal(renders,4);
});
test('forming price changes retain independent flow evidence until closed research changes',()=>{
 const x=setup();x.ctx.window.RegimeResearch={};let renders=0,updates=0;
 x.ctx.RegimeResearch={render(){renders++},updateRuntime(){updates++;return true}};vm.runInContext(slice('function renderStockResearch(', '\nfunction renderStock('),x.ctx);
 x.S.data.chart.panels[0].closed_presentation_sha256='stable-closed';x.ctx.renderStockResearch(x.S.data);
 x.S.data.chart.panels[0].presentation_sha256='forming-change';x.S.data.chart.panels[0].regime_research.runtime.forming_bars_excluded=1;x.ctx.renderStockResearch(x.S.data);
 assert.equal(renders,1);assert.equal(updates,1);
 x.S.data.chart.panels[0].closed_presentation_sha256='changed-research';x.ctx.renderStockResearch(x.S.data);assert.equal(renders,2);
});
test('live status uses admitted closed-bar count without scanning 23904 bars',()=>{
 const x=setup();x.ctx.PERIOD={day:'日线'};x.ctx.integer=String;x.ctx.text=(s,t)=>x.el(s).textContent=t;
 x.S.data.summary.live={received_at:'2026-11-15T10:00:00',latest_bar_at:'2026-11-13',confirmed_history_bars:1427};
 x.S.data.chart.panels[0].bars={filter(){throw Error('scanned old history')}};x.S.data.chart.panels[0].live_session.total_closed=23904;
 vm.runInContext(slice('function renderLiveStatus(', '\nfunction liveSnapshotToken('),x.ctx);x.ctx.renderLiveStatus();assert.ok(x.el('#live-quote-status').textContent.includes('23904'));
});
'''


class FrontendSnapshotDeliveryTests(unittest.TestCase):
    def test_conditional_delivery_and_research_state(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node.js is required')
        result=subprocess.run([node,'-e',NODE_TESTS,str(ROOT/'workbench/web/app.js'),str(ROOT/'workbench/web/regime-research.js')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('tests 22',result.stdout)


if __name__=='__main__':unittest.main()
