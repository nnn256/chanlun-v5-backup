"""Read-only loopback progress viewer for the F-drive market replay."""
from __future__ import annotations

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from urllib.parse import urlsplit

PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全市场分时历史回放</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#203d55;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:40px 24px}h1{font-size:30px;line-height:1.3;margin:12px 0}h2{font-size:17px;margin:0 0 12px}small,.muted{color:#637b8e}section{background:#fff;border:1px solid #dce5ed;padding:24px;margin-top:20px;border-radius:8px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.grid section{margin-top:0}progress{width:100%;height:12px;accent-color:#386683}.counts{font:26px/1.5 Consolas,monospace;margin:8px 0}.tag{display:inline-block;background:#e8eff5;padding:4px 10px;border-radius:4px;font-size:12px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px 6px;border-bottom:1px solid #e6edf3;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 Consolas,monospace}.error{color:#ac3f43}.grid{margin-top:24px}@media(max-width:650px){main{padding:24px 14px}h1{font-size:25px}.grid{grid-template-columns:1fr}section{padding:16px}table{font-size:12px}}</style>
<main><small>CHANLUN · 本地批量研究 · 不上传</small><h1>全市场，全部可得分钟历史。</h1><p>固定当前股票池 · 原生 1分钟 / 5分钟 · 每份计算结果独立复算后才计入通过</p><span class="tag" id="state">读取运行状态…</span> <small id="updated"></small>
<div class="grid"><section><h2>① 行情采集</h2><progress id="capture-bar"></progress><div class="counts" id="capture-count">—</div><div id="capture-detail" class="muted"></div></section><section><h2>② 计算与独立核验</h2><progress id="analysis-bar"></progress><div class="counts" id="analysis-count">—</div><div id="analysis-detail" class="muted"></div></section></div>
<section><h2>正在计算</h2><div id="active"></div></section><section><h2>GPU 行情校验</h2><p id="gpu-detail" class="muted">等待 CUDA 校验任务</p><p id="gpu-scope" class="muted"></p></section><section><h2>失败与不可用记录</h2><div id="failures"></div></section><section><h2>数据和时间口径</h2><p>没有“最近60日”裁切。起点为每只股票当前数据源实际返回的最早原生K线；不把未提供的分钟补成上市以来完整历史。当前股票池不包括所有历史退市证券。</p><p>信号在实际确认时才可用，成交只使用下一根原始开盘价假设。全天最高/最低价只作事后评估，不用于实时信号。重复、缺失或异常数据保留错误凭据。</p><p id="paths" class="muted"></p><details><summary>机器状态摘要</summary><pre id="raw"></pre></details></section><section><h2>计算资源</h2><p id="resources" class="muted">读取资源状态…</p><p id="resource-policy" class="muted"></p></section></main>
<script>const $=s=>document.querySelector(s),num=n=>Number(n||0).toLocaleString('zh-CN');let busy=false;async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/progress'),d=await r.json(),c=d.capture,a=d.analysis,g=d.gpu;$('#updated').textContent='本次读取 '+new Date().toLocaleString('zh-CN');$('#state').textContent=a?.state==='interrupted'?'已中断':(a?.state||c?.state||'准备中');$('#capture-bar').max=c?.requested||1;$('#capture-bar').value=c?.done||0;$('#capture-count').textContent=c?num(c.done)+' / '+num(c.requested):'等待采集任务';$('#capture-detail').textContent=c?'成功 '+num(c.complete)+' · 失败 '+num(c.failed)+' · 来源无历史 '+num(c.unavailable)+' · 已取 '+num(c.bars)+' 根K线':'';$('#analysis-bar').max=a?.requested||1;$('#analysis-bar').value=a?.verified||0;$('#analysis-count').textContent=a?num(a.verified)+' / '+num(a.requested):'等待计算任务';const stale=a?.state==='interrupted'?' · 上次进度距今 '+Math.floor((a.stale_seconds||0)/60)+' 分钟':'';$('#analysis-detail').textContent=a?'已独立核验 '+num(a.verified)+' · 运行 '+num(a.counts?.running)+' · 待数据 '+num(a.counts?.waiting_source)+' · 失败 '+num(a.failed)+' · 来源不可用 '+num(a.source_unavailable)+' · 核验K线 '+num(a.bars_verified)+stale:'';function table(holder,items){const el=$(holder);el.replaceChildren();if(!items.length){el.textContent='暂无记录';return;}const t=document.createElement('table');for(const item of items){const tr=document.createElement('tr');for(const k of ['symbol','period','state','stage','error']){const td=document.createElement('td');td.textContent=item[k]||'';tr.append(td);}t.append(tr);}el.append(t);}table('#active',d.active);table('#failures',d.failures);$('#gpu-detail').textContent=g?((g.gpu_device?.name||'CUDA设备')+' · '+num(g.done)+' / '+num(g.requested)+' 个股票周期 · 通过 '+num(g.passed)+' · 失败 '+num(g.failed)+' · '+num(g.bars)+' 根K线 · '+g.state):'CUDA全市场校验尚未开始';$('#gpu-scope').textContent=g?'仅含GPU OHLCV完整性及交易日高低点；CPU负责缠论结构递推。':'显卡只执行已验证的行情数据校验内核。';const sc=a?.scheduler;if(sc){$('#resources').textContent='CPU工作进程 '+num(sc.active_workers)+' / '+num(sc.max_workers)+' · 系统CPU '+(sc.cpu_percent==null?'未知':sc.cpu_percent.toFixed(0)+'%')+' · 空闲内存 '+num(Math.round((sc.available_memory_bytes||0)/1048576))+' MB';const why={ready_single:'运行单个任务',ready_parallel:'允许增加并行任务',worker_limit:'已达并行上限',cpu_busy_or_unknown:'等待CPU余量',reserving_memory:'为运行任务预留内存',waiting_memory:'等待可用内存',memory_unknown:'内存状态未知'};$('#resource-policy').textContent=(why[sc.admission_reason]||sc.admission_reason)+' · CPU缠论算法保留完整回放与独立复核';}else{$('#resources').textContent='等待调度器资源记录';$('#resource-policy').textContent='';}$('#paths').textContent='F盘目录：'+d.root;$('#raw').textContent=JSON.stringify(d,null,2);}catch(e){$('#state').textContent='读取失败：'+e.message;}finally{busy=false}}refresh();setInterval(refresh,5000);</script></html>'''


def snapshot(root):
    def read(path):
        if not path.is_file():return None
        value=json.loads(path.read_text(encoding='utf-8'))
        value.pop('entries',None)
        return value
    data={'root':str(root),'capture':read(root/'acquisition/acquisition-summary.json'),
          'analysis':read(root/'analysis/summary.json'),
          'gpu':read(root/'acceleration-20261117/gpu-audit/summary.json'),
          'active':[],'failures':[],
          'uploaded':False,'execution_allowed':False}
    database=root/'analysis/tasks.sqlite3'
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.row_factory=sqlite3.Row
            for field,query in [('active',"SELECT symbol,period,state,stage,error FROM tasks WHERE state='running' ORDER BY started_at DESC LIMIT 10"),
                                ('failures',"SELECT symbol,period,state,stage,error FROM tasks WHERE state IN ('failed','source_unavailable') ORDER BY updated_at DESC LIMIT 30")]:
                data[field]=[dict(row) for row in db.execute(query)]
    analysis=data['analysis']
    if analysis and analysis.get('state')=='running' and not data['active']:
        try:
            updated=datetime.fromisoformat(analysis['updated_at'])
            stale_seconds=max(0,int((datetime.now(updated.tzinfo)-updated).total_seconds()))
        except (KeyError,TypeError,ValueError):
            stale_seconds=0
        if stale_seconds>120:
            analysis['state']='interrupted'
            analysis['stale_seconds']=stale_seconds
            analysis['counts']={**analysis.get('counts',{}),'running':0}
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--port',type=int,default=8798);a=p.parse_args();root=a.root.resolve()
    (root/'progress-view.html').write_text(PAGE,encoding='utf-8')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            try:
                if path=='/':payload=PAGE.encode('utf-8');kind='text/html; charset=utf-8'
                elif path=='/api/progress':payload=json.dumps(snapshot(root),ensure_ascii=False).encode('utf-8');kind='application/json; charset=utf-8'
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(payload)))
                self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(payload)
            except (OSError,ValueError,sqlite3.Error) as e:self.send_error(503,str(e))
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    print(f'Local market progress http://127.0.0.1:{a.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
