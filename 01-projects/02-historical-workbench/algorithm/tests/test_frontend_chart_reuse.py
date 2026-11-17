"""Exercise real chart lifecycle and async export handlers under response races."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

NODE_TESTS = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const source=fs.readFileSync(process.argv[1],'utf8');
const slice=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
function element(){return {checked:false,disabled:false,textContent:'',replaceChildren(){},append(){}};}
function setup(){
 const els=new Map(),queue=new Map(),downloads=[],toasts=[];let serial=0,rebuilds=0;
 const el=s=>{if(!els.has(s))els.set(s,element());return els.get(s)};
 const panels=['day','30m','5m'].map((period,i)=>({period,presentation_sha256:String(i).repeat(64),bars:Array(i===2?23904:1427).fill({time:1}),live_session:{appended:0}}));
 const S={selected:'bj920000',period:'all',rank:'all',signalSide:'all',stockRequest:1,job:'',layers:{segments:true},data:{available:true,summary:{symbol:'bj920000',name:'安徽凤凰',algorithm:'V4'},chart:{panels}},charts:panels.map(p=>({p,chart:{timeScale:()=>({getVisibleLogicalRange:()=>({from:1,to:10}),getVisibleRange:()=>({from:1,to:10})})}}))};
 const ctx={S,$:el,$$:()=>[],window:{},document:{fonts:{ready:Promise.resolve()}},console:{error(){}},URLSearchParams,Blob,
  requestAnimationFrame:fn=>{queue.set(++serial,fn);return serial},cancelAnimationFrame:id=>queue.delete(id),
  disposeCharts:()=>{rebuilds++;throw Error('rebuild-requested')},download:(blob,name)=>downloads.push({blob,name}),toast:m=>toasts.push(m),exportPNG:()=>{},
  currentKlinePanel:()=>S.data?.chart?.panels.find(p=>p.period==='day'),PERIOD:{day:'日线'},integer:String};
 vm.createContext(ctx);
 vm.runInContext(slice('function chartPresentationIdentity(', '\nasync function selectPeriod('),ctx);
 S.chartIdentity=ctx.chartPresentationIdentity(panels);
 return {ctx,S,el,queue,downloads,toasts,rebuilds:()=>rebuilds};
}
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const flush=()=>new Promise(r=>setImmediate(r));

test('same certified complete panel presentation preserves all three chart instances',()=>{
 const x=setup(),old=x.S.charts.slice();
 x.S.data.chart.panels=x.S.data.chart.panels.map(p=>({...p,source_receipt:{received_at:'new'},live_session:{appended:0,resident:true}}));
 assert.equal(x.ctx.renderCharts(true),true);assert.equal(x.rebuilds(),0);assert.deepEqual(x.S.charts,old);
 assert.equal(x.S.charts[2].p.bars.length,23904);assert.equal(x.S.charts[2].p.source_receipt.received_at,'new');
});
for(const reason of ['forming-volume','closed-flag','bar-count','signal-state','geometry','research'])test('new presentation identity requires rebuilding: '+reason,()=>{
 const x=setup();x.S.data.chart.panels=x.S.data.chart.panels.map((p,i)=>i===2?{...p,presentation_sha256:reason}:p);
 assert.throws(()=>x.ctx.renderCharts(true),/rebuild-requested/);assert.equal(x.rebuilds(),1);
});
test('older server without certified presentation identity keeps full rebuild behavior',()=>{
 const x=setup();delete x.S.data.chart.panels[1].presentation_sha256;
 assert.throws(()=>x.ctx.renderCharts(true),/rebuild-requested/);assert.equal(x.rebuilds(),1);
});
test('filter and symbol changes cannot reuse an old chart',()=>{
 for(const change of [x=>x.S.rank=2,x=>x.S.signalSide='buy',x=>x.el('#show-review-objects').checked=true,x=>x.el('#signal-show-invalid').checked=true,x=>x.S.selected='sz000001']){
  const x=setup();change(x);assert.throws(()=>x.ctx.renderCharts(true),/rebuild-requested/);
 }
});
test('scroll and resize events are coalesced into one frame and cancellation is final',()=>{
 const x=setup();let draws=0;const task=x.ctx.frameDraw(()=>draws++);
 for(let i=0;i<30;i++)task.schedule();assert.equal(x.queue.size,1);
 const [id,run]=[...x.queue.entries()][0];x.queue.delete(id);run();assert.equal(draws,1);
 task.schedule();task.cancel();assert.equal(x.queue.size,0);task.schedule();assert.equal(x.queue.size,0);
});
test('viewport culling keeps spanning edges and offset history without trimming source data',()=>{
 const x=setup(),range={from:100,to:400};
 assert.equal(x.ctx.chartSpanVisible(0,1000,range),true);
 assert.equal(x.ctx.chartSpanVisible(0,10,range),false);
 assert.equal(x.ctx.chartSpanVisible(399,800,range),true);
 assert.equal(x.ctx.chartSpanVisible(1100,1200,range,1000),true);
 assert.equal(x.ctx.chartSpanVisible(0,10,null),true);
 const all=Array.from({length:23904},(_,index)=>({start:index,end:index}));
 assert.equal(all.filter(span=>x.ctx.chartSpanVisible(span.start,span.end,{from:23604,to:23912})).length,303);
 assert.equal(all.length,23904);
});
test('disposing a chart cancels queued work before removing the library instance',()=>{
 const x=setup(),events=[];x.S.charts=[{cancelDraw:()=>events.push('cancel'),observer:{disconnect:()=>events.push('disconnect')},chart:{remove:()=>events.push('remove')}}];
 vm.runInContext(slice('function disposeCharts(', '\nfunction clearStockDetail('),x.ctx);
 x.ctx.disposeCharts();assert.deepEqual(events,['cancel','disconnect','remove']);assert.equal(x.S.charts.length,0);assert.equal(x.S.chartIdentity,null);
});
test('JSON export keeps the requested symbol and filename while selection changes',async()=>{
 const x=setup(),pending=deferred();let path;x.ctx.api=p=>(path=p,pending.promise);
 vm.runInContext(slice("$('#export-json').onclick=", "$('#export-png').onclick="),x.ctx);
 const work=x.el('#export-json').onclick();x.S.selected='sz000001';x.S.data={available:true,summary:{symbol:'sz000001',name:'平安银行'},chart:{panels:[]}};
 pending.resolve({available:true,summary:{symbol:'bj920000'},evidence:{stock:'bj920000'}});await work;
 assert.equal(path,'/api/stock/bj920000?full=1');assert.equal(x.downloads[0].name,'安徽凤凰_V4_结构证据.json');
 assert.equal(JSON.parse(await x.downloads[0].blob.text()).summary.symbol,'bj920000');
});
test('JSON export rejects an incorrectly identified response',async()=>{
 const x=setup();x.ctx.api=async()=>({summary:{symbol:'sz000001'}});
 vm.runInContext(slice("$('#export-json').onclick=", "$('#export-png').onclick="),x.ctx);await x.el('#export-json').onclick();
 assert.equal(x.downloads.length,0);assert.ok(x.toasts[0].includes('股票与请求不一致'));
});
test('CSV export is named for the original stock after an async selection change',async()=>{
 const x=setup(),pending=deferred();let path;x.ctx.fetch=p=>(path=p,pending.promise);
 vm.runInContext(slice("$('#kline-csv').onclick=", "\n$('#kline-table-open')"),x.ctx);
 const work=x.el('#kline-csv').onclick();x.S.selected='sz000001';pending.resolve({ok:true,blob:async()=>new Blob(['old-stock-ohlcv'])});await work;
 assert.equal(path,'/api/kline-csv/bj920000?period=day');assert.equal(x.downloads[0].name,'bj920000_day_完整原始K线.csv');
});
test('late audit cannot write its result onto a newly selected stock',async()=>{
 const x=setup(),pending=deferred();x.ctx.api=()=>pending.promise;
 vm.runInContext(slice("$('#kline-audit').onclick=", "\n$('#kline-csv')"),x.ctx);
 const work=x.el('#kline-audit').onclick();x.S.selected='sz000001';x.S.stockRequest++;
 pending.resolve({source_state:'matched',compared_rows:1427});await work;assert.equal(x.el('#kline-integrity').textContent,'');
});
test('PNG export stops before rendering when selection changes during font loading',async()=>{
 const x=setup(),fonts=deferred();x.ctx.document.fonts.ready=fonts.promise;
 vm.runInContext(slice('async function exportPNG(', "\n$$('.nav')"),x.ctx);
 const work=x.ctx.exportPNG();x.S.selected='sz000001';x.S.stockRequest++;fonts.resolve();await work;
 assert.equal(x.downloads.length,0);assert.ok(x.toasts[0].includes('图表已更新'));assert.equal(x.el('#export-png').disabled,false);
});
'''


class FrontendChartReuseTests(unittest.TestCase):
    def test_chart_identity_frames_and_async_export_races(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js is required')
        result = subprocess.run([node, '-e', NODE_TESTS, str(ROOT / 'workbench/web/app.js')],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('tests 17', result.stdout)


if __name__ == '__main__':
    unittest.main()
