"""Finish only failed minute acquisitions and publish an explicit composite run.

Keeps the original 5,579-stock run immutable. Repaired results have their own
response/cache/quality receipts and computation fingerprint; successful old
results keep their old fingerprint, rather than being relabelled as newly run.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import gzip
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from chanmodel.engine import multilevel
from chanmodel.model import Config
from chanmodel.tdx_data import TdxClient,atomic_bytes,atomic_json,now_iso,sha256
from chanmodel.tdx_intraday import cache_intraday,load_daily_cache,normalize_intraday,fetch_intraday
from chanmodel.tdx_quality import prepare_intraday_response,POLICY
from intraday_scan import range_coverage


def implementation_hash():
    files=[ROOT/'chanmodel'/name for name in ['model.py','structure.py','segments.py','centers.py','signals.py','engine.py','tdx_data.py','tdx_intraday.py','tdx_quality.py']]+[Path(__file__).resolve()]
    return sha256(b''.join(p.name.encode()+p.read_bytes() for p in files))


def source_response(code,period,old_result,source_run,cache,client):
    meta_path=cache/'tdx'/period/'metadata'/f'{code}.json'
    raw_path=cache/'tdx'/period/'raw'/f'{code}.json.gz'
    if meta_path.exists() and raw_path.exists():
        meta=json.loads(meta_path.read_text(encoding='utf-8'));compressed=raw_path.read_bytes()
        if sha256(compressed)!=meta['raw_storage_sha256']:raise ValueError('source cache compressed hash mismatch')
        raw=gzip.decompress(compressed)
        if sha256(raw)!=meta['response_sha256']:raise ValueError('source cache response hash mismatch')
        return raw,{**meta,'recovery_origin':'verified_existing_cache','recovery_read_at':now_iso()}
    archived=source_run/'responses'/period/f'{code}.json.gz'
    if archived.exists():
        raw=gzip.decompress(archived.read_bytes());envelope=json.loads(raw)
        if envelope.get('code')==0 and isinstance(envelope.get('data'),dict):
            return raw,{'response_sha256':sha256(raw),'response_bytes':len(raw),'received_at':None,
                        'url':client.base_url+f'/api/kline-all/tdx?code={code}&type={period}',
                        'recovery_origin':'archived_failed_acquisition','recovery_read_at':now_iso(),
                        'archived_file':str(archived.resolve()),
                        'original_attempts':[x for x in old_result.get('attempts',[]) if x.get('period')==period],
                        'receipt_limitation':'Original response bytes exist; exact HTTP receive time/status were not retained by the old failed request.'}
    errors=[]
    for attempt in range(3):
        try:
            _,receipt,raw=fetch_intraday(client,code,period)
            return raw,{**receipt,'recovery_origin':'new_acquisition_for_old_cutoff','prior_recovery_errors':errors}
        except Exception as exc:
            errors.append({'at':now_iso(),'error':f'{type(exc).__name__}: {exc}'})
            if attempt==2:raise
            time.sleep(attempt+1)


def repair_stock(old_result,run,cache,output,base_url,engine_hash):
    code=old_result['symbol'];settings=run['settings'];as_of=datetime.fromisoformat(settings['as_of'])
    record={k:old_result[k] for k in ['symbol','exchange','code','name']}
    started=time.monotonic();sources={};datasets={};quality_records={}
    try:
        day_meta=json.loads((cache/'tdx/day/metadata'/f'{code}.json').read_text(encoding='utf-8'))
        if day_meta['closed_rows']==0:
            response=gzip.decompress(Path(day_meta['raw_path']).read_bytes())
            data=json.loads(response)
            if sha256(response)!=day_meta['response_sha256'] or data.get('code')!=0 or data['data']['count']!=0 or data['data']['list'] not in [None,[]]:
                raise ValueError('empty daily input lacks verified zero-count response')
            result={**record,'status':'source_unavailable','source_period':'day','response_sha256':day_meta['response_sha256'],
                    'source_metadata':day_meta,'reason':'No daily history at original acquisition; neither minute alignment nor historical daily replay can be fabricated.'}
            atomic_json(output/'repairs/stocks'/f'{code}.json',result)
            return result
        datasets['day'],sources['day']=load_daily_cache(cache,code,as_of)
        client=TdxClient(base_url,90)
        for period,level in [('minute30','30m'),('minute5','5m')]:
            raw,receipt=source_response(code,period,old_result,Path(run['source_run']),cache,client)
            envelope=json.loads(raw)
            if envelope.get('code')!=0:raise ValueError('non-success archived response')
            atomic_bytes(output/'repairs/responses'/period/f'{code}.json.gz',gzip.compress(raw,compresslevel=6,mtime=0))
            prepared,audit=prepare_intraday_response(envelope['data'],as_of,period,
                                                    quarantine_zero_activity=True,exclude_after_cutoff=True)
            audit.update(symbol=code,period=period,response_sha256=sha256(raw),
                         acquisition_origin=receipt['recovery_origin'],received_at=receipt.get('received_at'))
            audit_path=output/'repairs/quality'/period/f'{code}.json';atomic_json(audit_path,audit)
            bars,rows,quality=normalize_intraday(prepared,as_of,period)
            quality.update(original_response_rows=audit['original_rows'],quarantined_rows=audit['quarantined_rows'],
                           after_cutoff_rows_excluded=audit['after_cutoff_rows'],quality_policy=POLICY,
                           quality_audit_path=str(audit_path.resolve()),quality_audit_sha256=sha256(audit_path.read_bytes()),
                           raw_rows_semantics='retained rows after explicit quarantine/cutoff selection; original_response_rows records untouched source size',
                           cache_run_as_of=settings['as_of'],original_response_sha256=sha256(raw))
            sources[level]=cache_intraday(output/'repair_cache',code,period,rows,raw,receipt,quality)
            datasets[level]=bars;quality_records[level]=audit
            if not bars:raise ValueError(period+': no usable historical bars remain at saved cutoff')
        report=multilevel(datasets,('day','30m','5m'),settings['as_of'],Config(**settings['config']))
        parents={p['id']:p for p in report['levels']['day']['signal_candidates']}
        children={p['id']:p for p in report['levels']['30m']['signal_candidates']}
        for audit in report['interval_nesting_audits']:
            audit['daily_terminal_30m_coverage']=range_coverage(parents[audit['parent_signal']],datasets['day'],datasets['30m'])
            for match in audit['matches']:
                match['confirm_terminal_5m_coverage']=range_coverage(children[match['confirm_id']],datasets['30m'],datasets['5m'])
        result={**record,'status':'success','as_of':settings['as_of'],'processed_at':now_iso(),'engine_sha256':engine_hash,
                'periods':{level:{'bars':len(bars),'first_close':bars[0].closed_at,'last_close':bars[-1].closed_at,
                                  'strokes':len(report['levels'][level]['strokes']),'segments':len(report['levels'][level]['segments']),
                                  'centers':len(report['levels'][level]['centers']),'state':report['levels'][level]['current_state'],
                                  'active_candidate_count':sum(p['status']=='candidate' for p in report['levels'][level]['signal_candidates'])}
                           for level,bars in datasets.items()},'sources':sources,'interval_nesting_audits':report['interval_nesting_audits'],
                'nested_evidence_count':sum(a['nested_candidate_evidence'] for a in report['interval_nesting_audits']),
                'quality_policy':POLICY,'quarantined_rows':sum(x['quarantined_rows'] for x in quality_records.values()),
                'after_cutoff_rows_excluded':sum(x['after_cutoff_rows'] for x in quality_records.values()),
                'recovery_vintage':'Original cached responses when present; missing responses acquired later and explicitly truncated at saved cutoff.',
                'adjustment':'unadjusted','definition_mode':'multi_timeframe_structure_proxy','execution_allowed':False,
                'limitations':['Strict recursive trend types and genuine lower-level triggers remain unproven.',
                               'Excluded anomalous source rows create explicit gaps; no time/price substitution or padding.',
                               'Later acquisitions are not point-in-time data vintages.'],
                'elapsed_seconds':round(time.monotonic()-started,3)}
    except Exception as exc:
        result={**record,'status':'failed','error':f'{type(exc).__name__}: {exc}','sources':sources,'elapsed_seconds':round(time.monotonic()-started,3)}
    atomic_json(output/'repairs/stocks'/f'{code}.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True)
    parser.add_argument('--cache-dir',type=Path,default=ROOT/'market_data')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--base-url',default='http://127.0.0.1:18080')
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    if not 1<=args.workers<=4:parser.error('workers must be between 1 and 4 for targeted repairs')
    source=args.source_run.resolve();output=args.output_dir.resolve();cache=args.cache_dir.resolve()
    if source==output:parser.error('write composite results to a new output directory')
    output.mkdir(parents=True,exist_ok=True)
    run=json.loads((source/'run.json').read_text(encoding='utf-8'));run['source_run']=str(source)
    db=sqlite3.connect(source/'checkpoint.sqlite3')
    prior={code:json.loads(raw) for code,raw in db.execute('SELECT symbol,result FROM stocks')};db.close()
    wanted={r['symbol'] for r in run['universe']}
    if set(prior)!=wanted:raise ValueError('source checkpoint does not account for every universe symbol')
    good=[x for x in prior.values() if x['status']=='success'];todo=[x for x in prior.values() if x['status']!='success']
    contract=implementation_hash()
    composite={'created_at':now_iso(),'source_run':str(source),'source_run_sha256':sha256((source/'run.json').read_bytes()),
               'universe':run['universe'],'coverage':run['coverage'],'as_of':run['settings']['as_of'],
               'repair_engine_sha256':contract,'config':run['settings']['config'],'base_url':args.base_url,
               'quality_policy':POLICY,'immutable_old_results':True}
    atomic_json(output/'run.json',composite)
    repaired=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(repair_stock,record,run,cache,output,args.base_url,contract) for record in todo]
        for future in as_completed(futures):
            result=future.result();repaired.append(result)
            print(json.dumps({'symbol':result['symbol'],'status':result['status'],'quarantined':result.get('quarantined_rows'),
                              'bars':{k:v['bars'] for k,v in result.get('periods',{}).items()},'error':result.get('error')},ensure_ascii=False),flush=True)
    entries=[]
    for record in sorted(good+repaired,key=lambda r:r['symbol']):
        old=record['symbol'] in {x['symbol'] for x in good}
        path=(source/'stocks' if old else output/'repairs/stocks')/f"{record['symbol']}.json"
        saved=json.loads(path.read_text(encoding='utf-8'))
        if old and saved!=record:raise ValueError('original stock JSON differs from original checkpoint')
        entries.append({'symbol':record['symbol'],'status':record['status'],'result_file':str(path),'result_sha256':sha256(path.read_bytes()),
                        'provenance':'original_verified_run' if old else 'targeted_repair','engine_sha256':record.get('engine_sha256')})
    atomic_json(output/'manifest.json',entries)
    results=good+repaired;success=[r for r in results if r['status']=='success'];unavailable=[r for r in results if r['status']=='source_unavailable'];failures=[r for r in results if r['status']=='failed']
    summary={'updated_at':now_iso(),'as_of':composite['as_of'],'universe_count':len(wanted),'processed':len(results),
             'success':len(success),'original_success_reused':len(good),'repaired_success':sum(r['status']=='success' for r in repaired),
             'source_unavailable':unavailable,'unavailable_count':len(unavailable),'failed':len(failures),'failures':failures,'pending':0,
             'total_bars':{level:sum(r['periods'][level]['bars'] for r in success) for level in ['day','30m','5m']},
             'quarantined_rows':sum(r.get('quarantined_rows',0) for r in repaired),
             'after_cutoff_rows_excluded':sum(r.get('after_cutoff_rows_excluded',0) for r in repaired),
             'status':'complete_with_source_unavailable' if not failures and unavailable else 'complete' if not failures else 'needs_attention',
             'nested_evidence_count':sum(r['nested_evidence_count'] for r in success),'definition_mode':'multi_timeframe_structure_proxy',
             'execution_allowed':False,'data_origin':'TDX archived and retried responses; explicit quality exclusions; no generated bars'}
    atomic_json(output/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ['status','success','repaired_success','unavailable_count','failed','total_bars','quarantined_rows']},ensure_ascii=False),flush=True)
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
