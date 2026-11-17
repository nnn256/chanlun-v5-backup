"""Compare random real TDX stocks: resident append vs fixed full-prefix replay."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import random
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.reference_engine import ReferenceSession, analyze_reference, COMMIT, PROFILE
from chanmodel.release import APP_VERSION
from chanmodel.tdx_data import CN,TdxClient,normalize_daily

OUT=Path(__file__).resolve().parents[2]/'artifacts/chanlun-v4.2.2-validation-20261113'
SEED=20261113
RNG=random.Random(SEED)
AS_OF=datetime.now(CN)
UNIVERSE=json.loads((ROOT/'runs/tdx-all-a-20261106/universe.json').read_text(encoding='utf-8'))['records']
POOL=[r for r in UNIVERSE if not r['symbol'].startswith('sh688827')]
RNG.shuffle(POOL)
CLIENT=TdxClient(timeout=90)


def shape(report):
    return {key:report[key] for key in ('base','hierarchy','signals','observed_signal_events','geometry_review')}


def main():
    selected=[];attempts=[];results=[]
    for record in POOL:
        if len(selected)==2:break
        try:
            data,receipt,raw=CLIENT.request_retry('/api/kline-all/tdx',
                {'code':record['symbol'],'type':'day'},attempts=2)
            bars,rows,quality=normalize_daily(data,AS_OF)
            if len(bars)<200:raise ValueError('fewer than 200 closed daily bars')
            selected.append((record,bars,rows,receipt,raw,quality))
            attempts.append({'symbol':record['symbol'],'state':'selected','closed_bars':len(bars),
                             'first':bars[0].closed_at,'last':bars[-1].closed_at,
                             'response_sha256':receipt['response_sha256']})
        except Exception as exc:
            attempts.append({'symbol':record['symbol'],'state':'skipped','error':f'{type(exc).__name__}: {exc}'})
    if len(selected)!=2:raise RuntimeError(f'only {len(selected)} random securities returned complete test history')
    for record,bars,rows,receipt,raw,quality in selected:
        tested_symbol=record['symbol']
        session=ReferenceSession('day',observe=True);input_hash=hashlib.sha256(raw).hexdigest()
        checkpoints=sorted(set(max(80,min(len(bars)-1,round((len(bars)-1)*part))) for part in (.34,.67,.9,1)))
        proofs=[];full_elapsed=[];incremental_elapsed=[];last=-1
        for position,bar in enumerate(bars):
            start=time.perf_counter();session.append(bar)
            if position!=last+1:raise AssertionError('append position skipped')
            incremental_elapsed.append(time.perf_counter()-start);last=position
            if position not in checkpoints:continue
            prefix=bars[:position+1];cutoff=prefix[-1].closed_at
            started=time.perf_counter()
            full=analyze_reference(record['symbol'],'day',prefix,cutoff,input_hash,'tdx','unadjusted')
            full_elapsed.append(time.perf_counter()-started)
            fast=session.snapshot(record['symbol'],cutoff,'tdx','unadjusted',input_hash)
            for key in shape(full):
                if fast[key]!=full[key]:
                    raise AssertionError(f'{tested_symbol} prefix {position} differs in {key}')
            proofs.append({'closed_prefix_bars':position+1,'cutoff':cutoff,
                           'native_strokes':len(fast['base']['strokes']),
                           'native_segments':len(fast['base']['segments']),
                           'native_signals':len(fast['signals']),
                           'equivalent_fields':sorted(shape(full)),'status':'exact_match'})
        results.append({'symbol':record['symbol'],'name':record['name'],'source_response_sha256':receipt['response_sha256'],
                        'provider_bars':len(bars),'first_bar':bars[0].closed_at,'last_bar':bars[-1].closed_at,
                        'seed_historical_batch_seconds':round(sum(incremental_elapsed),6),
                        'median_one_bar_append_ms':round(sorted(incremental_elapsed)[len(incremental_elapsed)//2]*1000,4),
                        'full_replay_median_seconds':round(sorted(full_elapsed)[len(full_elapsed)//2],4),
                        'equivalence_checkpoints':proofs,'rule_profile':PROFILE,'engine_commit':COMMIT,
                        'strict_original_equivalence_proven':False})
    result={'version':APP_VERSION,'selection_seed':SEED,'as_of':AS_OF.isoformat(),'selection_attempts':attempts,
            'stocks':results,'status':'pass','semantics':'incremental output exactly matches the same pinned engine on full prefixes; this is equivalence, not proof of original-theory truth'}
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'RANDOM-TWO-STOCK-VERIFICATION.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'stocks':[{'symbol':x['symbol'],'bars':x['provider_bars'],
        'median_append_ms':x['median_one_bar_append_ms'],'full_median_seconds':x['full_replay_median_seconds'],
        'checkpoints':len(x['equivalence_checkpoints'])} for x in results]},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
