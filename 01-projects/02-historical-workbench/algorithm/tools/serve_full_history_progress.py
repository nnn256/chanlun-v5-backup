"""Read-only loopback viewer for both daily pipelines and the existing minute run."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_ROOT = Path('D:/ChanlunFullHistory-20261117')
DEFAULT_MINUTE_ROOT = Path('F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday')


def _read(path):
    path = Path(path)
    if not path.is_file():
        return None, None
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError('summary is not a JSON object')
        return value, None
    except (OSError, ValueError) as error:
        return None, type(error).__name__ + ': ' + str(error)


def _first(value, *names):
    for name in names:
        if value.get(name) is not None:
            return value[name]
    return None


def _stage(path, kind, planned_total=None, exclusions=None):
    value, error = _read(path)
    stage = {'kind':kind,'path':str(path),'available':value is not None,
             'state':value.get('state','unknown') if value else 'pending',
             'planned_total':planned_total,'requested':None,'processed':None,
             'successful':None,'failed':None,'excluded':exclusions,
             'processing_complete':None,'successful_coverage_complete':None,
             'bars':None,'updated_at':None,'raw':value}
    if error:
        stage.update(state='unreadable',error=error)
    if value is None:
        return stage
    counts = value.get('counts') or {}
    stage.update(requested=_first(value,'requested','total'),updated_at=value.get('updated_at'),
                 processing_complete=value.get('processing_complete'),
                 successful_coverage_complete=value.get('successful_coverage_complete'))
    stage.update(first_date=value.get('first_date'),last_date=value.get('last_date'),
                 last_date_counts=value.get('last_date_counts'))
    if kind == 'acquisition':
        stage.update(processed=_first(value,'processed','done'),
                     successful=_first(value,'complete','completed','success'),
                     failed=value.get('failed'),excluded=_first(value,'unavailable','source_unavailable'),
                     bars=value.get('bars'))
    elif kind == 'v4':
        completed=value.get('completed');failed=value.get('failed')
        stage.update(processed=(completed+failed if isinstance(completed,int) and isinstance(failed,int) else None),
                     successful=completed,failed=failed,bars=value.get('bars'))
        if 'state' not in value:
            stage['state']='completed' if value.get('processing_complete') is True else 'waiting_memory' if value.get('resources',{}).get('waiting_for_memory') else 'running'
    elif kind == 'v3':
        stage.update(processed=value.get('processed'),successful=counts.get('complete',0),
                     failed=counts.get('failed',0),bars=value.get('bars'),
                     excluded=counts.get('source_unavailable',0)+counts.get('insufficient_history',0))
    elif kind == 'intraday':
        stage.update(processed=(value.get('verified',0)+value.get('failed',0)+value.get('source_unavailable',0)),
                     successful=value.get('verified'),failed=value.get('failed'),
                     excluded=value.get('source_unavailable'),bars=value.get('bars_verified'))
    return stage


def snapshot(root=DEFAULT_ROOT, minute_root=None):
    root=Path(root).resolve()
    config,config_error=_read(root/'pipeline.json')
    status,status_error=_read(root/'status.json')
    coverage,coverage_error=_read(root/'inputs/coverage.json')
    config=config or {}
    minute=Path(minute_root or config.get('minute_run') or DEFAULT_MINUTE_ROOT).resolve()
    total=config.get('securities') or (status or {}).get('securities')
    excluded=(len(coverage.get('v4_excluded',[])) if coverage is not None else None)
    stages={
        'acquisition':_stage(root/'acquisition/summary.json','acquisition',total),
        'v4':_stage(root/'v4-daily/summary.json','v4',coverage.get('v4_eligible') if coverage else None,excluded),
        'v3':_stage(root/'v3-daily/summary.json','v3',total),
        'intraday':_stage(minute/'analysis/summary.json','intraday')}
    for key in ('v4','v3'):
        if not stages[key]['available']:
            stages[key]['waiting_for']='acquisition' if not stages['acquisition']['processing_complete'] else 'v4' if key=='v3' and not stages['v4']['processing_complete'] else 'dispatch'
    return {'schema':'both_systems_full_history_progress_v1','root':str(root),'minute_root':str(minute),
            'observed_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'pipeline':status or {'state':'pending'},'configuration':{
                key:config.get(key) for key in ('schema','created_at','cutoff','securities','history','scheduling')},
            'coverage':coverage,'stages':stages,
            'read_errors':{key:value for key,value in [('pipeline',config_error),('status',status_error),('coverage',coverage_error)] if value},
            'scope':{'daily':'all closed daily candles actually returned, from each security’s earliest saved date',
                     'intraday':'existing independent 1m/5m full-returned-history run; its status is observed only',
                     'membership':'frozen current listed universe; historical delisted membership is not reconstructed',
                     'listing_inception_coverage_verified':False,'history_truncated':False},
            'read_only':True,'uploaded':False,'execution_allowed':False}


PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全部历史测算进度</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#203d55;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:40px 24px}h1{font-size:30px;line-height:1.3;margin:12px 0}h2{font-size:17px;margin:0 0 12px}small,.muted{color:#637b8e}section{background:#fff;border:1px solid #dce5ed;padding:24px;margin-top:20px;border-radius:8px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px}.grid section{margin-top:0}progress{width:100%;height:12px;accent-color:#386683}.counts{font:26px/1.5 Consolas,monospace;margin:8px 0}.tag{display:inline-block;background:#e8eff5;padding:4px 10px;border-radius:4px;font-size:12px}.stage-state{float:right;font-size:12px;color:#637b8e}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:10px 6px;border-bottom:1px solid #e6edf3;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 Consolas,monospace}.error{color:#ac3f43}.detail{font-size:13px;line-height:1.9}a{color:#386683}@media(max-width:650px){main{padding:24px 14px}h1{font-size:25px}.grid{grid-template-columns:1fr}section{padding:16px}table{font-size:12px}}</style>
<main><small>CHANLUN · 本地批量研究 · 只读进度</small><h1>全部历史测算</h1><p>日线依次采集 → V4 回放 → 量测 v3 回放；既有 1分钟 / 5分钟任务独立运行。</p><span class="tag" id="state">读取运行状态…</span> <small id="updated"></small>
<div class="grid" id="stages"></div>
<section><h2>当前任务与资源</h2><div id="active" class="detail muted">等待任务状态</div></section>
<section><h2>覆盖与未纳入记录</h2><div id="coverage" class="detail muted"></div><div id="exclusions"></div></section>
<section><h2>各阶段失败记录</h2><div id="failures" class="detail muted"></div></section>
<section><h2>历史范围</h2><p>每只股票从接口实际返回并保存的最早闭合K线开始，不裁成近期窗口。未返回的历史不补零，当前股票池也不代表包含全部历史退市证券。</p><p>采集完成、算法处理完成和全证券成功分开显示。V4 日线不足50根的证券列为未纳入；量测 v3 不足3根单独记录。图表和结果用于复现既定规则。</p><p id="paths" class="muted"></p><details><summary>机器状态摘要</summary><pre id="raw"></pre></details></section></main>
<script>
const $=s=>document.querySelector(s),n=v=>v==null?'—':Number(v).toLocaleString('zh-CN');
const names={acquisition:'① 日线全历史采集',v4:'② V4 原生因果回放',v3:'③ 量测 v3 递归回放',intraday:'独立任务 · 1分钟 / 5分钟'};
const labels={pending:'等待前序阶段',prepared:'已准备',running:'运行中',completed:'处理完成',waiting_memory:'等待可用内存',paused:'已暂停',stopped:'已停止',failed:'失败',unreadable:'状态文件暂不可读'};
let busy=false;
function add(parent,tag,text,cls){const el=document.createElement(tag);if(cls)el.className=cls;el.textContent=text;parent.append(el);return el;}
function table(holder,rows,fields){holder.replaceChildren();if(!rows.length){add(holder,'p','暂无记录','muted');return;}const table=add(holder,'table','');for(const row of rows){const tr=add(table,'tr','');for(const field of fields)add(tr,'td',row[field]??'—');}}
async function refresh(){if(busy)return;busy=true;try{const response=await fetch('/api/progress',{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);const d=await response.json();$('#updated').textContent='本次读取 '+new Date(d.observed_at).toLocaleString('zh-CN');$('#state').textContent=(labels[d.pipeline.state]||d.pipeline.state)+' · '+(d.pipeline.stage||'日线流水线');const host=$('#stages');host.replaceChildren();for(const [key,s] of Object.entries(d.stages)){const box=add(host,'section','');const title=add(box,'h2',names[key]);add(title,'span',labels[s.state]||s.state,'stage-state');const progress=add(box,'progress','');progress.max=s.requested||s.planned_total||1;progress.value=s.processed||0;add(box,'div',s.available?n(s.processed)+' / '+n(s.requested??s.planned_total):'尚未开始'+(s.planned_total?' · 计划 '+n(s.planned_total):''),'counts');add(box,'div',s.available?'成功 '+n(s.successful)+' · 失败 '+n(s.failed)+' · 未纳入 / 来源不可用 '+n(s.excluded)+' · K线 '+n(s.bars):s.error||({acquisition:'等待全市场日线采集完成',v4:'等待V4回放完成',dispatch:'等待阶段派发'}[s.waiting_for]||'等待实际运行摘要'),'detail muted');if(s.first_date||s.last_date)add(box,'p','历史范围 '+(s.first_date||'—')+' 至 '+(s.last_date||'—'),'detail muted');if(s.processing_complete===true)add(box,'p','处理完成；'+(s.successful_coverage_complete===true?'本阶段计划证券全部成功':'请核对失败与覆盖范围'),'detail muted');}
const active=[];for(const [key,s] of Object.entries(d.stages)){const raw=s.raw;if(!raw)continue;if(raw.active)active.push(names[key]+'：'+raw.active.symbol+' · '+n(raw.active.bars_done)+' / '+n(raw.active.bars_total)+' 根');if(raw.resources)active.push(names[key]+'：活动进程 '+n(raw.resources.active_workers)+' · '+(raw.resources.waiting_for_memory?'等待内存':'按资源预算派发'));if(raw.scheduler)active.push(names[key]+'：活动进程 '+n(raw.scheduler.active_workers)+' / '+n(raw.scheduler.max_workers)+' · 空闲内存 '+(raw.scheduler.available_memory_bytes==null?'—':(raw.scheduler.available_memory_bytes/1024**3).toFixed(2)+' GB'));for(const task of raw.active_tasks||[])active.push(names[key]+'：'+task.symbol+' '+task.period+' · '+(task.stage||''));}$('#active').textContent=active.length?active.join('；'):'尚无活动任务摘要';const c=d.coverage;const dates=c?.last_dates?Object.entries(c.last_dates).map(([date,count])=>date+'：'+n(count)+'只').join('；'):'';$('#coverage').textContent=c?'计划 '+n(c.requested)+' 只 · 有效来源 '+n(c.source_pairs)+' · V4可回放 '+n(c.v4_eligible)+' · 未纳入 '+n(c.v4_excluded?.length)+' · 来源声明 '+n(c.declared_bars)+' 根日线'+(dates?'。各股末根日期 '+dates:''):'采集后生成逐股覆盖清单；当前不推断已齐全。';table($('#exclusions'),(c?.v4_excluded||[]).slice(0,40),['symbol','bars','reason']);const issues=[];for(const [key,s] of Object.entries(d.stages)){for(const row of s.raw?.failed_records||[])issues.push({stage:names[key],...row});if(s.error)issues.push({stage:names[key],error:s.error});}table($('#failures'),issues.slice(0,40),['stage','symbol','period','error']);$('#paths').textContent='日线：'+d.root+' · 分钟：'+d.minute_root;$('#raw').textContent=JSON.stringify(d,null,2);}catch(error){$('#state').textContent='读取失败：'+error.message;}finally{busy=false}}
refresh();setInterval(refresh,5000);
</script></html>'''


def make_handler(root,minute_root=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/':
                payload=PAGE.encode('utf-8');kind='text/html; charset=utf-8'
            elif path=='/health':
                payload=json.dumps({'status':'ok','service':'full-history-progress','read_only':True}).encode();kind='application/json; charset=utf-8'
            elif path=='/api/progress':
                payload=json.dumps(snapshot(root,minute_root),ensure_ascii=False,allow_nan=False).encode('utf-8');kind='application/json; charset=utf-8'
            else:
                self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers();self.wfile.write(payload)
        def log_message(self,*args):
            pass
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--minute-root',type=Path)
    parser.add_argument('--port',type=int,default=8801)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(args.root,args.minute_root))
    print(f'Full history progress http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
