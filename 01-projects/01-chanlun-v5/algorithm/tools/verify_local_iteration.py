"""Read-only local validation; never tunes, edits, promotes, or publishes code."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):value.update(chunk)
    return value.hexdigest()


def canonical(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))


def read_json(path):
    path=Path(path)
    raw=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
    return json.loads(raw)


def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


class Verification:
    def __init__(self,output):
        self.output=output
        self.failures=[]
        self.checks=[]
        self.commands=[]

    def check(self,name,passed,**evidence):
        record={'name':name,'passed':bool(passed),**evidence}
        self.checks.append(record)
        if not passed:self.failures.append(record)
        return bool(passed)

    def command(self,name,args,timeout=1800):
        stdout=self.output/(name+'.stdout.log');stderr=self.output/(name+'.stderr.log')
        start=time.perf_counter();code=None;error=None
        with stdout.open('w',encoding='utf-8') as out,stderr.open('w',encoding='utf-8') as err:
            try:
                result=subprocess.run(args,cwd=ROOT,stdout=out,stderr=err,timeout=timeout,
                                      encoding='utf-8',errors='replace')
                code=result.returncode
            except (OSError,subprocess.TimeoutExpired) as exc:
                error=f'{type(exc).__name__}: {exc}';err.write(error+'\n')
        record={'name':name,'argv':[str(arg) for arg in args],'cwd':str(ROOT),
                'exit_code':code,'seconds':round(time.perf_counter()-start,3),
                'stdout':str(stdout),'stderr':str(stderr),'error':error}
        self.commands.append(record)
        self.check(name,code==0,**{key:value for key,value in record.items() if key!='name'})

    def section(self,name,fn):
        try:return fn()
        except Exception as exc:
            self.check(name,False,error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
            return None


def _split(date,splits):
    return next((name for name,bounds in splits.items() if bounds[0]<=date<=bounds[1]),None)


def _sample_receipts(receipts):
    complete=sorted((row for row in receipts if row.get('state')=='complete'),key=lambda row:row['symbol'])
    if not complete:return []
    indices={0,*[round((len(complete)-1)*i/8) for i in range(1,9)]}
    return [complete[index] for index in sorted(indices)]


def verify_study(v,study):
    manifest=read_json(study/'manifest.json');summary=read_json(study/'summary.json')
    receipts=read_json(study/'stock-receipts.json')
    config=manifest['config'];config_hash=hashlib.sha256(canonical(config).encode()).hexdigest()
    v.check('study_configuration',config_hash==manifest['config_sha256']==summary['configuration_sha256'],
            computed=config_hash,manifest=manifest['config_sha256'],summary=summary['configuration_sha256'])
    v.check('study_local_only',not manifest.get('external_publish') and not manifest.get('auto_source_updates')
            and not summary.get('execution_allowed') and not summary.get('external_publish'))
    v.check('study_code_receipts_agree',manifest.get('code_sha256')==summary.get('code_sha256'))
    frozen=study/'frozen-code'
    has_frozen=frozen.is_dir()
    if has_frozen:
        for relative,expected in manifest.get('code_sha256',{}).items():
            target=(frozen/relative).resolve()
            if not target.is_relative_to(frozen.resolve()):raise ValueError('frozen code path escapes study')
            actual=digest(target) if target.is_file() else None
            v.check('frozen_code:'+relative,actual==expected,expected=expected,actual=actual,path=str(target))
    else:v.checks.append({'name':'frozen_code','passed':None,'state':'not_run','reason':'study has no frozen-code snapshot'})
    complete=[row for row in receipts if row.get('state')=='complete']
    totals={'total':len(receipts),'completed':len(complete),'failed':len(receipts)-len(complete),
            'bars':sum(row.get('bars',0) for row in complete),
            'events':sum(row.get('event_count',0) for row in complete),
            'event_horizon_observations':sum(row.get('evaluated_event_horizons',0) for row in complete)}
    v.check('receipt_totals',all(summary.get(key)==value for key,value in totals.items()),
            computed=totals,summary={key:summary.get(key) for key in totals})
    exclusions=Counter();metric_counts=Counter()
    for row in complete:
        exclusions.update(row.get('excluded',{}))
        metric_counts.update({key:value['count'] for key,value in row.get('stats',{}).items()})
    v.check('excluded_totals',dict(exclusions)==summary.get('excluded',{}))
    expected_counts={key:value['count'] for key,value in summary.get('metrics',{}).items()}
    v.check('metric_observation_totals',dict(metric_counts)==expected_counts,
            groups=len(metric_counts))
    splits=summary['splits'];sampled=[]
    for receipt in _sample_receipts(receipts):
        symbol=receipt['symbol'];path=study/'stocks'/(symbol+'.json.gz')
        artifact_hash=digest(path)
        v.check('artifact_sha256:'+symbol,artifact_hash==receipt['artifact_sha256'],actual=artifact_hash)
        payload=read_json(path)
        v.check('artifact_receipt:'+symbol,payload['event_count']==receipt['event_count']
                and payload['source']['source_sha256']==receipt['source_sha256'])
        outcomes=payload['event_outcomes'];bad=[];evaluated=0
        for index,row in enumerate(outcomes):
            if row.get('state')!='evaluated':continue
            evaluated+=1
            try:
                observed=datetime.fromisoformat(row['observed_at'])
                entry=datetime.fromisoformat(row['entry_time']);exit_=datetime.fromisoformat(row['exit_time'])
                if not observed<entry<=exit_:bad.append([index,'temporal_order'])
                assigned=[_split(point.date().isoformat(),splits) for point in (observed,entry,exit_)]
                if any(value!=row['split'] for value in assigned):bad.append([index,'chronological_split'])
                if not row['observed_index']<row['entry_index']<=row['exit_index']:
                    bad.append([index,'index_order'])
                for field in ('entry_open','exit_close','window_high','window_low'):
                    price=row.get(field)
                    if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
                        bad.append([index,'invalid_price:'+field])
                breadth=row.get('breadth')
                if breadth and datetime.fromisoformat(breadth['available_at'])>observed:
                    bad.append([index,'future_breadth'])
            except (KeyError,TypeError,ValueError) as exc:bad.append([index,str(exc)])
        v.check('sample_outcomes:'+symbol,not bad and evaluated==receipt['evaluated_event_horizons'],
                evaluated=evaluated,expected=receipt['evaluated_event_horizons'],failures=bad)
        sampled.append(symbol)
    v.check('sample_selection',bool(sampled),symbols=sampled,selection='first plus eight evenly spaced fixed positions')
    if not has_frozen:
        return {'path':str(study),'totals':totals,'sampled_symbols':sampled,'parity_sources':[],
                'frozen_hashes_verified':False,'full_artifact_hash_scan':False}
    reader=load_module(frozen/'tools/run_regime_research.py','local_verify_frozen_study_reader')
    frozen_engine=load_module(frozen/'chanmodel/regime_research.py','local_verify_frozen_regime')
    from chanmodel import regime_research as current
    sources=manifest['sources'];parity=[]
    for prefix in ('sh','sz','bj'):
        source=next((source for source in sources if source['symbol'].startswith(prefix)),None)
        if source is None:
            v.check('engine_parity:'+prefix,False,error='no deterministic source');continue
        symbol=source['symbol'];rows,receipt=reader.read_daily_rows(source['path'],config['cutoff'])
        source_receipt=next((row for row in complete if row['symbol']==symbol),None)
        v.check('parity_source_sha256:'+symbol,source_receipt is not None
                and receipt['source_sha256']==source_receipt['source_sha256'],actual=receipt['source_sha256'])
        old=frozen_engine.analyze_regimes(rows,symbol=symbol);new=current.analyze_regimes(rows,symbol=symbol)
        old_series=old['series'];new_series=new['series'];differences=[]
        if len(old_series)!=len(new_series):differences.append('series_count')
        for index,(left,right) in enumerate(zip(old_series,new_series)):
            for key in ('state','features','rules','invalidation','closed_at','close','evidence_available_at'):
                if left.get(key)!=right.get(key):differences.append(f'series[{index}].{key}')
        if len(old['events'])!=len(new['events']):differences.append('event_count')
        for index,(left,right) in enumerate(zip(old['events'],new['events'])):
            if {key:value for key,value in left.items() if key not in ('id','side')}!={key:value for key,value in right.items() if key not in ('id','side')}:
                differences.append(f'events[{index}]')
            risk=any(marker in left.get('event','') for marker in ('invalidated','expired'))
            if left.get('side')!=right.get('side') and not (risk and right.get('side')=='risk'):
                differences.append(f'events[{index}].side')
            for event in (left,right):
                price=event.get('price')
                if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
                    differences.append(f'events[{index}].price')
        v.check('engine_parity:'+symbol,not differences,bars=len(rows),events=len(new['events']),failures=differences)
        parity.append({'symbol':symbol,'bars':len(rows),'events':len(new['events'])})
    return {'path':str(study),'totals':totals,'sampled_symbols':sampled,'parity_sources':parity,
            'frozen_hashes_verified':True,'full_artifact_hash_scan':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True,help='Must not exist; preserves each validation run.')
    parser.add_argument('--study-dir',type=Path,help='Completed immutable local event-study directory.')
    parser.add_argument('--skip-suite',action='store_true',help='Skip unittest discover for a cheap independent rerun.')
    args=parser.parse_args();output=args.output_dir.resolve()
    if output.exists():parser.error('output directory already exists; choose a fresh path')
    output.mkdir(parents=True);v=Verification(output);start=time.perf_counter()
    from chanmodel.release import APP_VERSION,APP_LABEL
    code_paths=sorted({*ROOT.glob('chanmodel/*.py'),*ROOT.glob('workbench/*.py'),
                       *ROOT.glob('workbench/web/*.js'),ROOT/'desktop_app.py',Path(__file__).resolve()})
    code_hashes={path.relative_to(ROOT).as_posix():digest(path) for path in code_paths if path.is_file()}
    if not args.skip_suite:v.command('unittest-discover',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'])
    node=shutil.which('node')
    if node:
        for name in ('app.js','signal-chart.js','regime-research.js'):
            v.command('node-check-'+name,[node,'--check',str(ROOT/'workbench/web'/name)],timeout=60)
    else:v.checks.append({'name':'node-syntax','passed':None,'state':'not_run','reason':'node unavailable'})
    study_result=None
    if args.study_dir:study_result=v.section('study_verification',lambda:verify_study(v,args.study_dir.resolve()))
    changed=[relative for relative,expected in code_hashes.items()
             if not (ROOT/relative).is_file() or digest(ROOT/relative)!=expected]
    v.check('source_snapshot_stable',not changed,changed_paths=changed)
    result={'version':1,'release_version':APP_VERSION,'release':APP_LABEL,
            'created_at':datetime.now(timezone.utc).isoformat(),'seconds':round(time.perf_counter()-start,3),
            'status':'failed' if v.failures else 'passed','suite_skipped':args.skip_suite,
            'source_root':str(ROOT),'code_sha256':code_hashes,'commands':v.commands,'checks':v.checks,
            'failures':v.failures,'study':study_result,'external_publish':False,'auto_source_updates':False,
            'limits':['No network acquisition, executable trading, installer mutation, source edits or promotion is performed.',
                      'Study receipts are aggregated in full; only nine deterministic artifact payloads are hashed and inspected.',
                      'Frozen/current whole-history engine parity covers one deterministic SH, SZ and BJ source, not every symbol.',
                      'Event outcomes are retrospective observations on latest-vintage unadjusted cache, not calibrated forecasts.']}
    (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'checks':len(v.checks),'failures':len(v.failures),
                      'verification':str(output/'verification.json')},ensure_ascii=False))
    return 1 if v.failures else 0


if __name__=='__main__':raise SystemExit(main())
