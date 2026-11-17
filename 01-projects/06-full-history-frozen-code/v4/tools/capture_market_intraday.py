"""Hash-checked resumable native 1m/5m acquisition; no synthetic history.

The frozen provider-listed universe is explicit and is not a point-in-time
delisted universe. Each provider's earliest/latest native bar is reported.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.tdx_data import TdxClient,atomic_bytes,atomic_json,now_iso,normalize_universe,symbol
from chanmodel.tdx_intraday import normalize_intraday,cache_intraday
from chanmodel.v2.io import load_cache_series
from chanmodel.tdx_quality import prepare_intraday_response


PERIODS={'1m':'minute1','5m':'minute5'}


@contextmanager
def capture_output_lock(output):
    """Hold one OS lock per output; the file remains for crash-safe reuse."""
    path=Path(output)/'acquisition.lock';path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b');stream.seek(0);stream.write(b'1');stream.flush();stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:raise ValueError('another acquisition is already writing this output') from exc
        else:
            import fcntl
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:raise ValueError('another acquisition is already writing this output') from exc
        yield
    finally:stream.close()


def capture_one(symbol_code,period,cache,cutoff,base_url='http://127.0.0.1:65004',*,
                resume=True,quarantine_zero_activity=False,timeout=20,attempts=3):
    """Acquire and normalize one full native period; independently resumable."""
    code=symbol(symbol_code)
    if period not in PERIODS:raise ValueError('capture supports native 1m and 5m')
    observed=datetime.fromisoformat(cutoff.replace('Z','+00:00'))
    if observed.tzinfo is None:raise ValueError('cutoff needs timezone')
    cache=Path(cache);meta=cache/'tdx'/PERIODS[period]/'metadata'/(code+'.json')
    if resume and meta.exists():
        try:
            series,receipt=load_cache_series(cache,code,period)
            saved=json.loads(meta.read_text(encoding='utf-8'))
            if saved.get('capture_cutoff')!=cutoff or saved.get('quarantine_zero_activity',False)!=quarantine_zero_activity:
                raise ValueError('capture profile/cutoff differs')
            raw_path=Path(saved['raw_path'])
            compressed=raw_path.read_bytes()
            if hashlib.sha256(compressed).hexdigest()!=saved['raw_storage_sha256']:
                raise ValueError('raw storage hash differs')
            raw=gzip.decompress(compressed)
            if hashlib.sha256(raw).hexdigest()!=saved['response_sha256']:
                raise ValueError('raw source response hash differs')
            result=saved['acquisition_result']
            return {**result,'resumed':True}
        except (OSError,ValueError,KeyError):
            pass  # A mere existing filename never proves successful capture.
    start=time.monotonic();client=TdxClient(base_url,timeout=timeout)
    try:
        data,receipt,raw=client.request_retry('/api/kline-all/tdx',{'code':code,'type':PERIODS[period]},attempts=attempts)
        prepared,audit=prepare_intraday_response(data,observed,PERIODS[period],
            quarantine_zero_activity=quarantine_zero_activity,exclude_after_cutoff=True)
        bars,rows,quality=normalize_intraday(prepared,observed,PERIODS[period])
        if not bars:
            # An empty native source is real unavailability, not a successful
            # replay with invented zero/flat candles.
            empty=cache/'unavailable'/period/(code+'.json.gz')
            atomic_bytes(empty,gzip.compress(raw,mtime=0))
            result={'symbol':code,'period':period,'state':'unavailable','bars':0,
                    'reason':'provider_returned_no_native_closed_history','raw_path':str(empty),
                    'raw_sha256':hashlib.sha256(raw).hexdigest(),'receipt':receipt,
                    'seconds':round(time.monotonic()-start,3),'resumed':False}
            atomic_json(cache/'capture-status'/period/(code+'.json'),result)
            return result
        quality.update(capture_cutoff=cutoff,quality_policy=audit,
                       quarantine_zero_activity=quarantine_zero_activity)
        metadata=cache_intraday(cache,code,PERIODS[period],rows,raw,receipt,quality)
        csv=Path(metadata['csv_path']);stored=Path(metadata['raw_path'])
        result={'symbol':code,'period':period,'state':'complete','bars':len(bars),
                'raw_rows':audit['original_rows'],'quarantined_rows':audit['quarantined_rows'],
                'excluded_after_cutoff_rows':audit['after_cutoff_rows'],
                'first':bars[0].closed_at,'last':bars[-1].closed_at,
                'raw_bytes':len(raw),'raw_gzip_bytes':stored.stat().st_size,
                'csv_gzip_bytes':csv.stat().st_size,'stored_bytes':stored.stat().st_size+csv.stat().st_size,
                'raw_sha256':metadata['response_sha256'],'csv_sha256':metadata['csv_sha256'],
                'csv_storage_sha256':metadata['csv_storage_sha256'],
                'metadata_file':str(meta.resolve()),'source':'tdx_native_ohlcv',
                'coverage_claim':'all native bars returned at this cutoff; no listing-inception proof',
                'seconds':round(time.monotonic()-start,3),'resumed':False}
        metadata['acquisition_result']=result;atomic_json(meta,metadata)
        atomic_json(cache/'capture-status'/period/(code+'.json'),result)
        return result
    except Exception as exc:
        result={'symbol':code,'period':period,'state':'failed','error':f'{type(exc).__name__}: {exc}',
                'seconds':round(time.monotonic()-start,3),'resumed':False}
        atomic_json(cache/'capture-status'/period/(code+'.json'),result)
        return result


def load_universe(path):
    value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    rows=value if isinstance(value,list) else value.get('records',value.get('rows'))
    if not isinstance(rows,list) or not rows:raise ValueError('universe must contain a nonempty rows/records list')
    result=[]
    for row in rows:
        code=symbol(row if isinstance(row,str) else row['symbol'])
        if code not in result:result.append(code)
    return result


def run_capture(universe,output,cutoff,base_url,workers=1,*,resume=True,periods=('1m','5m'),
                quarantine_zero_activity=False,min_free_gb=10):
    with capture_output_lock(output):
        return _run_capture(universe,output,cutoff,base_url,workers,resume=resume,periods=periods,
                            quarantine_zero_activity=quarantine_zero_activity,min_free_gb=min_free_gb)


def _run_capture(universe,output,cutoff,base_url,workers=1,*,resume=True,periods=('1m','5m'),
                quarantine_zero_activity=False,min_free_gb=10):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    cache=output/'market_data';codes=load_universe(universe)
    if workers not in range(1,5):raise ValueError('safe acquisition workers must be 1..4')
    if any(p not in PERIODS for p in periods):raise ValueError('unknown native acquisition period')
    requested=[(code,p) for code in codes for p in periods]
    source_hash=hashlib.sha256(Path(universe).read_bytes()).hexdigest()
    signature={'universe_sha256':source_hash,'cutoff':cutoff,'periods':list(periods),
               'source':base_url,'quarantine_zero_activity':quarantine_zero_activity}
    manifest=output/'acquisition-profile.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8'))!=signature:
        raise ValueError('output belongs to a different frozen universe or acquisition profile')
    atomic_json(manifest,signature)
    entries={};started=now_iso();began=time.monotonic();halt=None
    journal=output/'acquisition-events.jsonl'

    def save(state):
        values=list(entries.values());counts={name:sum(v['state']==name for v in values) for name in ['complete','failed','unavailable']}
        summary={'state':state,'processing_complete':state=='completed','requested':len(requested),
                 'securities':len(codes),'periods':list(periods),'done':len(values),**counts,
                 'bars':sum(v.get('bars',0) for v in values),'stored_bytes':sum(v.get('stored_bytes',0) for v in values),
                 'started_at':started,'updated_at':now_iso(),'seconds':round(time.monotonic()-began,3),
                 'universe_sha256':source_hash,'cutoff':cutoff,'source':base_url,
                 'execution_allowed':False,'uploaded':False,
                 'detail_journal':str(journal.resolve()),'status_final_count_verified':False,
                 'stop_file':str((output/'STOP').resolve()),
                 'coverage_semantics':'frozen current provider universe and all native history actually returned; not all-delisted history'}
        if state=='completed':
            verified=sum((cache/'capture-status'/period/(code+'.json')).is_file() for code,period in requested)
            summary['status_files_present']=verified
            summary['status_final_count_verified']=verified==len(requested)
            atomic_json(output/'acquisition-results.json',{'profile':signature,'entries':values})
            summary['detail_results']=str((output/'acquisition-results.json').resolve())
        atomic_json(output/'acquisition-summary.json',summary)
        # Stable alias consumed by the separate follow-cache replay runner.
        atomic_json(output/'summary.json',summary)
        return summary

    save('running')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Limit in-flight native responses; full 1m OHLC can be several MB.
        futures={};todo=iter(requested);exhausted=False
        while futures or not exhausted:
            if (output/'STOP').exists():halt='stopped_by_request';exhausted=True
            while len(futures)<workers and not exhausted and halt is None:
                try:code,period=next(todo)
                except StopIteration:exhausted=True;break
                if shutil.disk_usage(output).free<min_free_gb*1024**3:
                    halt='stopped_low_disk';exhausted=True;break
                f=pool.submit(capture_one,code,period,cache,cutoff,base_url,resume=resume,
                              quarantine_zero_activity=quarantine_zero_activity)
                futures[f]=(code,period)
            if not futures:break
            done=next(as_completed(futures));code,period=futures.pop(done)
            value=done.result();entries[code+'|'+period]=value
            with journal.open('a',encoding='utf-8',newline='\n') as stream:
                stream.write(json.dumps({'observed_at':now_iso(),**value},ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
            summary=save('running')
            if len(entries)%10==0 or len(entries)==len(requested):
                print(json.dumps({k:summary[k] for k in ['done','requested','complete','failed','unavailable','bars','stored_bytes']},ensure_ascii=False),flush=True)
    return {**save(halt or 'completed'),'entries':list(entries.values())}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--universe',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cutoff',required=True)
    p.add_argument('--base-url',default='http://127.0.0.1:65004')
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--period',action='append',choices=('1m','5m'))
    p.add_argument('--no-resume',action='store_true')
    p.add_argument('--quarantine-zero-activity',action='store_true')
    p.add_argument('--min-free-gb',type=float,default=10)
    args=p.parse_args()
    result=run_capture(args.universe,args.output,args.cutoff,args.base_url,args.workers,
                       resume=not args.no_resume,periods=tuple(args.period or ['1m','5m']),
                       quarantine_zero_activity=args.quarantine_zero_activity,min_free_gb=args.min_free_gb)
    print(json.dumps({k:v for k,v in result.items() if k!='entries'},ensure_ascii=False,indent=2))
    if result['failed']:raise SystemExit(1)


if __name__=='__main__':main()
