"""Exercise cache recovery and history downloads with real frontend functions."""
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.test_stock_load_ui import NODE_TESTS

ROOT=Path(__file__).resolve().parents[1]
HARNESS=NODE_TESTS.split("test('live selection shows dated saved snapshot before live all resolves'")[0]

OFFLINE_TESTS=r'''
const local=(symbol='bj920000')=>({...saved(symbol),summary:{...saved(symbol).summary,mode:'local_cache',local_cache:{as_of:'2026-11-12',source:'verified_saved_csv'}}});
async function tickTimer(x,milliseconds){const item=[...x.timeouts].find(([,t])=>t.ms===milliseconds);assert.ok(item,'expected timer '+milliseconds);x.timeouts.delete(item[0]);item[1].fn();await flush();}

test('missing artifact builds local history before live and keeps it after network failure',async()=>{
 let pending;const historical=local();const x=setup((path,options)=>
  path.startsWith('/api/live-stock/')?(pending=deferred(options)).promise:
  path.startsWith('/api/local-stock/status/')?Promise.resolve(historical):
  path.startsWith('/api/local-stock/')?Promise.resolve({available:false,state:'building',symbol:'bj920000',status_url:'/api/local-stock/status/task-1'}):Promise.resolve({available:false}));
 x.el('#live-quote').checked=true;const work=x.context.selectStock('bj920000');await flush();
 assert.equal(x.calls.length,2);assert.ok(x.el('#stock-empty').textContent.includes('本地历史'));
 await tickTimer(x,1000);assert.equal(x.renders.length,1);assert.equal(x.S.data,historical);assert.equal(x.S.data.summary.live,undefined);
 assert.equal(x.calls.at(-1).path,'/api/live-stock/bj920000?period=all');pending.reject(Error('TDX disconnected'));await work;
 assert.equal(x.S.data,historical);assert.equal(x.el('#stock-detail').hidden,false);assert.ok(x.el('#live-quote-status').textContent.includes('保留已显示的历史快照'));
 assert.equal(x.timeouts.size+x.intervals.size,0);
});

test('artifact eight-second wait is separate from local build and live sixty-second wait',async()=>{
 let stored,network;const x=setup((path,options)=>path.startsWith('/api/stock/')?(stored=deferred(options)).promise:
  path.startsWith('/api/local-stock/')?Promise.resolve(local()):(network=deferred(options)).promise);
 x.el('#live-quote').checked=true;const work=x.context.selectStock('bj920000');await flush();await tickTimer(x,8000);
 assert.equal(x.renders.length,1);assert.equal(x.S.data.summary.mode,'local_cache');assert.equal(x.S.stockLoading,true);
 assert.ok([...x.timeouts.values()].some(timer=>timer.ms===60000));assert.ok(![...x.timeouts.values()].some(timer=>timer.ms===120000));
 await tickTimer(x,60000);await work;assert.equal(x.S.data.summary.mode,'local_cache');assert.equal(x.S.stockLoading,false);
 assert.ok(x.el('#live-quote-status').textContent.includes('60秒'));
});

test('explicit local mode never fetches live including forced refresh polling',async()=>{
 const x=setup(path=>Promise.resolve(path.startsWith('/api/local-stock/')?local():{available:false}));
 x.S.localOnly=true;x.el('#live-quote').checked=true;await x.context.selectStock('bj920000');
 await x.context.quoteTick(true);assert.equal(x.calls.length,2);assert.equal(x.calls.some(c=>c.path.startsWith('/api/live-stock/')),false);
 assert.equal(x.S.data.summary.mode,'local_cache');assert.equal(x.S.stockRetryAt,null);
});

test('local mode preserves chosen minute period by requesting it rather than only saved daily',async()=>{
 const x=setup(path=>Promise.resolve(path.startsWith('/api/local-stock/')?{...local(),chart:{panels:[{period:'day'},{period:'5m'}]}}:saved()));
 x.S.localOnly=true;x.S.period='5m';await x.context.selectStock('bj920000');
 assert.equal(x.calls[1].path,'/api/local-stock/bj920000?period=5m');assert.equal(x.S.period,'5m');assert.equal(x.S.data.chart.panels[1].period,'5m');
});

test('switching stock aborts a pending local build poll and ignores its late answer',async()=>{
 let oldStatus;const x=setup((path,options)=>path.startsWith('/api/stock/')?Promise.resolve({available:false}):
  path.includes('sz000001')?Promise.resolve(local('sz000001')):
  path.startsWith('/api/local-stock/status/')?(oldStatus=deferred(options,true)).promise:
  Promise.resolve({available:false,state:'building',status_url:'/api/local-stock/status/old'}));
 x.S.localOnly=true;const first=x.context.selectStock('bj920000');await flush();await tickTimer(x,1000);
 const second=x.context.selectStock('sz000001');await second;oldStatus.resolve(local());await first;
 assert.equal(x.S.data.summary.symbol,'sz000001');assert.equal(x.renders.length,1);assert.equal(x.timeouts.size+x.intervals.size,0);
});

test('local cache identity cannot introduce another stock or claim real-time freshness',async()=>{
 for(const invalid of [local('sz000001'),{...local(),summary:{...local().summary,live:{received_at:'now'}}}]){
  const x=setup(path=>Promise.resolve(path.startsWith('/api/local-stock/')?invalid:{available:false}));x.S.localOnly=true;
  await x.context.selectStock('bj920000');assert.equal(x.renders.length,0);assert.equal(x.S.data,null);assert.ok(x.el('#stock-empty').textContent.includes('本地'));
 }
});

test('full local evidence stays requested when a background build needs status polling',async()=>{
 const x=setup(path=>Promise.resolve(path.includes('/status/')?{...local(),evidence:{source_receipts:{day:'verified'}}}:{available:false,state:'building',status_url:'/api/local-stock/status/full-1'}));
 const work=x.context.awaitLocalStock('bj920000','day',undefined,()=>{},true);await flush();
 assert.equal(x.calls[0].path,'/api/local-stock/bj920000?period=day&full=1');
 await tickTimer(x,1000);const result=await work;assert.equal(x.calls[1].path,'/api/local-stock/status/full-1?full=1');
 assert.equal(result.evidence.source_receipts.day,'verified');
});

function historySetup(handler){
 const x=setup(handler),downloads=[];x.el('#history-export-scope').value='all';x.el('#history-export-period').value='day';
 x.context.node=(tag,cls,text)=>({...element(),tag,textContent:text||'',className:cls||'',click(){downloads.push(this)}});
 vm.runInContext(source.slice(source.indexOf('function setLocalHistoryMode(')),x.context);
 return {...x,downloads};
}

test('history inventory polls background status and displays complete source count',async()=>{
 const x=historySetup(path=>Promise.resolve(path.includes('/status/')?{state:'ready',total:5580,securities:5580,rows:Array(200).fill({})}:{state:'building',status_url:'/api/history/inventory/status/scan-1'}));
 const work=x.context.inspectLocalHistory();await flush();await tickTimer(x,2000);await work;
 assert.equal(x.calls.length,2);assert.ok(x.el('#history-inventory-status').textContent.includes('5580'));assert.equal(x.el('#history-inventory').disabled,false);
});

test('history ZIP download uses a direct browser link and preserves partial coverage label',async()=>{
 const x=historySetup(path=>Promise.resolve(path==='/api/history/exports'?{id:'archive-1',state:'building',status_url:'/api/history/exports/archive-1'}:
  {state:'partial',download_url:'/api/history/exports/archive-1/download',bytes:1024**2,files:42,sha256:'a'.repeat(64)}));
 const work=x.context.exportLocalHistory();await flush();await tickTimer(x,1000);await work;
 assert.equal(x.downloads.length,1);assert.equal(x.downloads[0].href,'/api/history/exports/archive-1/download');assert.equal(x.downloads[0].download,'');
 assert.ok(x.el('#history-export-status').children[0].textContent.includes('部分导出'));assert.equal(x.el('#history-export').disabled,false);
 assert.equal(x.calls.length,2);assert.equal(x.calls.some(c=>c.path.endsWith('/download')),false);
});

test('cancel history wait keeps the background export and never fetches a large ZIP blob',async()=>{
 const x=historySetup(()=>Promise.resolve({state:'building',status_url:'/api/history/exports/archive-1'}));
 const work=x.context.exportLocalHistory();await flush();x.S.historyExportController.abort();await work;
 assert.equal(x.downloads.length,0);assert.equal(x.calls.length,1);assert.ok(x.el('#history-export-status').textContent.includes('后台任务'));
 assert.equal(x.el('#history-export').disabled,false);
});

test('history server responses cannot send the browser to an untrusted download URL',async()=>{
 const x=historySetup(()=>Promise.resolve({state:'ready',status_url:'/api/history/exports/archive-1',download_url:'https://example.invalid/history.zip'}));
 await x.context.exportLocalHistory();assert.equal(x.downloads.length,0);assert.ok(x.el('#history-export-status').textContent.includes('下载地址无效'));
});
'''


class OfflineStockUiTests(unittest.TestCase):
    def test_offline_cache_recovery_and_history_export_behaviors(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node.js required')
        result=subprocess.run([node,'-e',HARNESS+OFFLINE_TESTS,str(ROOT/'workbench/web/app.js')],cwd=ROOT,
            capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('tests 11',result.stdout)


if __name__=='__main__':unittest.main()
