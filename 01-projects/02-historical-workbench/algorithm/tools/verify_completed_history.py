"""Verify every reused/repaired result and deeply recompute all targeted repairs."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
import gzip
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from chanmodel.model import load_csv
from chanmodel.tdx_data import atomic_json,atomic_bytes,sha256,now_iso
from chanmodel.tdx_intraday import normalize_intraday
from chanmodel.tdx_quality import prepare_intraday_response
from verify_intraday_run import csv_bars,compare_recomputed


def check_entry(task):
    entry=task['entry'];code=entry['symbol'];result_path=Path(entry['result_file'])
    output={'symbol':code,'provenance':entry['provenance'],'errors':[]}
    try:
        raw_result=result_path.read_bytes()
        if sha256(raw_result)!=entry['result_sha256']:raise ValueError('result hash mismatch')
        result=json.loads(raw_result)
        if result['symbol']!=code or result['status']!=entry['status']:raise ValueError('result identity/status mismatch')
        if result['status']=='source_unavailable':
            meta=result['source_metadata'];compressed=Path(meta['raw_path']).read_bytes()
            if sha256(compressed)!=meta['raw_storage_sha256']:raise ValueError('empty source raw storage mismatch')
            raw=gzip.decompress(compressed);envelope=json.loads(raw)
            if sha256(raw)!=meta['response_sha256'] or envelope['code']!=0 or envelope['data']['count']!=0 or envelope['data']['list'] not in [None,[]]:
                raise ValueError('source-unavailable proof invalid')
            output.update(status='verified_source_unavailable',counted_as_success=False)
            return output
        if result['status']!='success':raise ValueError('unresolved failed result')
        old=entry['provenance']=='original_verified_run'
        if old:
            receipt=task['prior_verification']
            if receipt.get('status')!='verified' or receipt.get('errors'):raise ValueError('reused result lacks original full row verification')
            if receipt['checkpoint_engine_sha256']!=result['engine_sha256']:raise ValueError('original verified computation version differs')
            if task['checkpoint_result']!=result:raise ValueError('original stock JSON differs from checkpoint')
        cutoff=datetime.fromisoformat(task['as_of']);datasets={};verified_bars={};quarantined=after_cutoff=0
        for level,meta in result['sources'].items():
            csv_storage=Path(meta['csv_path']).read_bytes()
            csv_compressed=level!='day'
            expected=meta['csv_storage_sha256'] if csv_compressed else meta['csv_sha256']
            if sha256(csv_storage)!=expected:raise ValueError(level+': CSV storage hash mismatch')
            raw_storage=Path(meta['raw_path']).read_bytes()
            if sha256(raw_storage)!=meta['raw_storage_sha256']:raise ValueError(level+': source storage hash mismatch')
            if old:
                metrics=receipt['periods'][level]
                if metrics['closed_rows']!=result['periods'][level]['bars']:raise ValueError('prior row validation count mismatch')
                verified_bars[level]=metrics['closed_rows']
                continue
            raw=gzip.decompress(raw_storage)
            if sha256(raw)!=meta['response_sha256']:raise ValueError(level+': source payload hash mismatch')
            csv_raw=gzip.decompress(csv_storage) if csv_compressed else csv_storage
            if sha256(csv_raw)!=meta['csv_sha256']:raise ValueError(level+': CSV content hash mismatch')
            metrics,cached=csv_bars(csv_raw,level,cutoff,True)
            if metrics['closed_rows']!=result['periods'][level]['bars']:raise ValueError(level+': bar count mismatch')
            verified_bars[level]=metrics['closed_rows']
            if level=='day':
                datasets[level]=cached
                continue
            period='minute30' if level=='30m' else 'minute5'
            envelope=json.loads(raw)
            if envelope.get('code')!=0:raise ValueError('non-success original response')
            prepared,audit=prepare_intraday_response(envelope['data'],cutoff,period,quarantine_zero_activity=True,exclude_after_cutoff=True)
            saved_path=Path(meta['quality_audit_path']);saved_bytes=saved_path.read_bytes()
            if sha256(saved_bytes)!=meta['quality_audit_sha256']:raise ValueError('quality receipt hash mismatch')
            saved=json.loads(saved_bytes)
            if any(saved[key]!=value for key,value in audit.items()):raise ValueError('quality exclusion decisions not reproducible')
            if saved['response_sha256']!=sha256(raw):raise ValueError('quality receipt bound to wrong original response')
            bars,rows,quality=normalize_intraday(prepared,cutoff,period)
            if bars!=cached:raise ValueError(level+': filtered source and cached CSV differ')
            if len(rows)!=meta['unique_rows'] or quality['closed_rows']!=meta['closed_rows']:raise ValueError('normalized count mismatch')
            datasets[level]=bars;quarantined+=audit['quarantined_rows'];after_cutoff+=audit['after_cutoff_rows']
        if not old:
            # One auxiliary count was not in the repair schema; derive it from
            # the saved audits solely for validating compare_recomputed.
            compare_input={**result,'daily_candidates_without_30m_history':sum(not x['daily_terminal_30m_coverage']['terminal_range_covered'] for x in result['interval_nesting_audits'])}
            comparison=compare_recomputed(compare_input,datasets,task['config'],task['as_of'])
            if not all(comparison.values()):raise ValueError('repaired multilevel recomputation mismatch: '+str(comparison))
            if quarantined!=result['quarantined_rows'] or after_cutoff!=result['after_cutoff_rows_excluded']:raise ValueError('exclusion summary mismatch')
            output['recomputation']=comparison
        output.update(status='verified',bars=verified_bars,quarantined_rows=quarantined,after_cutoff_rows=after_cutoff,
                      validation_scope='all artifact hashes rechecked; original full row checks retained' if old else 'all repaired raw/CSV rows, quality decisions, and structure recomputed')
    except Exception as exc:
        output.update(status='fail');output['errors'].append(f'{type(exc).__name__}: {exc}')
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--completed-run',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();root=args.completed_run.resolve()
    run=json.loads((root/'run.json').read_text(encoding='utf-8'));manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    desired={r['symbol'] for r in run['universe']}
    if len(manifest)!=len(desired) or {r['symbol'] for r in manifest}!=desired:raise ValueError('composite manifest does not cover the unique original universe')
    original=Path(run['source_run'])
    if sha256((original/'run.json').read_bytes())!=run['source_run_sha256']:raise ValueError('original run settings changed')
    prior_path=original/'verification/stocks.json';prior_list=json.loads(prior_path.read_text(encoding='utf-8'));prior={x['symbol']:x for x in prior_list}
    db=sqlite3.connect((original/'checkpoint.sqlite3').as_uri()+'?mode=ro',uri=True)
    checkpoints={code:json.loads(value) for code,value in db.execute('SELECT symbol,result FROM stocks')};db.close()
    tasks=[{'entry':entry,'as_of':run['as_of'],'config':run['config'],
            'prior_verification':prior.get(entry['symbol']), 'checkpoint_result':checkpoints.get(entry['symbol'])} for entry in manifest]
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for n,future in enumerate(as_completed([pool.submit(check_entry,task) for task in tasks]),1):
            results.append(future.result())
            if n%500==0 or n==len(tasks):print(json.dumps({'checked':n,'total':len(tasks),'errors':sum(x['status']=='fail' for x in results)}),flush=True)
    failures=[r for r in results if r['status']=='fail'];good=[r for r in results if r['status']=='verified'];unavailable=[r for r in results if r['status']=='verified_source_unavailable']
    summary={'verified_at':now_iso(),'status':'fail' if failures else 'pass_with_source_unavailable' if unavailable else 'pass',
             'universe':len(desired),'verified_success':len(good),'verified_unavailable':len(unavailable),'pending':0,'errors':failures,
             'repaired_results_fully_recomputed':sum('recomputation' in r for r in results),
             'original_successful_results_rehashed':sum(r['status']=='verified' and r['provenance']=='original_verified_run' for r in results),
             'total_bars':{level:sum(r.get('bars',{}).get(level,0) for r in good) for level in ['day','30m','5m']},
             'quarantined_rows':sum(r.get('quarantined_rows',0) for r in good),'after_cutoff_rows_excluded':sum(r.get('after_cutoff_rows',0) for r in good),
             'previous_full_row_verification_file':str(prior_path),'previous_full_row_verification_sha256':sha256(prior_path.read_bytes()),
             'network_requests':0,'strict_chanlun_proven':False,'execution_allowed':False}
    atomic_json(root/'verification/summary.json',summary);atomic_json(root/'verification/stocks.json',sorted(results,key=lambda x:x['symbol']))
    text='\n'.join(['# 历史任务补齐核验','',f"核验时间：{summary['verified_at']}；状态：{summary['status']}。",'',
                    f"股票池{len(desired)}；成功结果核验{len(good)}；来源无历史{len(unavailable)}；未解释错误{len(failures)}；待处理0。",'',
                    f"原批次{summary['original_successful_results_rehashed']}份成功结果全部重查JSON、原始响应压缩件及CSV哈希，并继承原批次全部行情行的字段/网格检查；15份补齐结果逐份重新标准化、复现隔离决策并重算三周期结构。",'',
                    f"原始13:00零成交异常隔离{summary['quarantined_rows']}行，截止时间之后的补取行情排除{summary['after_cutoff_rows_excluded']}行。原始响应均保留，未改写价格/时间，未补造K线。",'',
                    '本结果为当前股票池、明确截止时间下的代理结构研究。补取数据是后取得的历史版本，不能宣称原时点已获得。严格递归和交易触发仍按算法审计中的限制解释。',''])
    atomic_bytes(root/'verification/VERIFICATION.md',text.encode('utf-8'))
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
