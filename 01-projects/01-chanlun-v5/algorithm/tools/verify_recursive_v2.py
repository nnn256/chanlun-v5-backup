"""Real-cache regression and certificate/causality verification for v2."""
from dataclasses import replace
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import sys
import time
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.engine import multilevel as legacy_multilevel
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.engine import analyze,multiframe,replay,replay_multiframe
from chanmodel.v2.series import validate_multiframe,derive_series
from chanmodel.tdx_data import atomic_json


def main():
    out=ROOT/'artifacts/recursive-v2-20261107';out.mkdir(parents=True,exist_ok=True)
    cutoff='2026-11-06T02:03:45+08:00';cache=ROOT/'market_data';started=time.monotonic();checks=[]
    codes=['sz000001','sh600519','bj920002','sh600531','sh600000','sz000002']
    for code in codes:
        inputs={};receipts={}
        for period in ['day','30m','5m']:inputs[period],receipts[period]=load_cache_series(cache,code,period)
        day_report=analyze(inputs['day'],cutoff)
        if day_report['certificate_audit']['errors']:raise AssertionError('certificate audit failed')
        multi=multiframe(inputs,('day','30m','5m'),cutoff,volume_tolerance=1000)
        checks.append({'symbol':code,'bars':{k:len(v.bars) for k,v in inputs.items()},'input_receipts':receipts,
                       'day_certificate_audit':day_report['certificate_audit'],
                       'day_rank_counts':[{'rank':x['rank'],'completed_types':len(x['completed_types']),
                                           'certified_centers':len(x['centers']),'completed_movement_views':len(x['movement_views']['completed_types'])} for x in day_report['hierarchy']['levels']],
                       'multiframe_state':multi['state'],'trigger_states':dict(Counter(x['state'] for x in multi['signals'])),
                       'pairs':[{key:p[key] for key in ['parent_period','child_period','state','matched_parent_bars','mismatched_parent_bars','incomplete_parent_bars','price_tolerance','volume_tolerance']} for p in multi['data_contract']['pairs']]})
        atomic_json(ROOT/'runs/recursive-v2-20261107'/f'{code}-day.json',day_report)
        atomic_json(ROOT/'runs/recursive-v2-20261107'/f'{code}-validated-multiframe.json',multi)
        print(json.dumps({'symbol':code,'certificate_state':day_report['certificate_audit']['state'],'multiframe_state':multi['state'],'triggers':checks[-1]['trigger_states']},ensure_ascii=False),flush=True)
    daily,_=load_cache_series(cache,'sz000001','day')
    duplicate={role:replace(daily,period=role) for role in ['day','30m','5m']}
    duplicate_checks=[]
    for name,call in [('v2_contract',lambda:validate_multiframe(duplicate,('day','30m','5m'),cutoff)),
                      ('legacy_guard',lambda:legacy_multilevel({k:list(s.bars) for k,s in duplicate.items()},('day','30m','5m'),cutoff))]:
        try:call()
        except ValueError as exc:duplicate_checks.append({'entry':name,'rejected':True,'error':str(exc)})
        else:raise AssertionError('duplicate timeframe case accepted')
    short=replace(daily,bars=daily.bars[:500]);long=replace(daily,bars=daily.bars[:600])
    _,short_events=replay(short);_,long_events=replay(long)
    if short_events!=[e for e in long_events if e['observed_index']<500]:raise AssertionError('future rewrote prefix ledger')
    if not short_events:raise AssertionError('causality sample unexpectedly has no events')
    for boundary in [150,300,500,600]:
        prefix=replace(daily,bars=daily.bars[:boundary]);latest,events=replay(prefix)
        direct=analyze(daily,daily.bars[boundary-1].closed_at)
        if latest['hierarchy']!=direct['hierarchy'] or latest['signals']!=direct['signals']:raise AssertionError('reference prefix computation differs from cutoff query')
    # Derived candles are aggregation of actual source rows, not generated
    # prices. Demonstrate exact zero-volume-tolerance reconciliation.
    five,_=load_cache_series(cache,'sz000001','5m')
    thirty=derive_series(five,'30m',cutoff);day=derive_series(thirty,'day',cutoff)
    derived=validate_multiframe({'day':day,'30m':thirty,'5m':five},('day','30m','5m'),cutoff,volume_tolerance=0)
    if derived['state']!='verified':raise AssertionError('exact observed-source aggregation failed')
    decision_times=[b.closed_at for b in day.bars[-5:]]
    dataset={'day':day,'30m':thirty,'5m':five}
    _,early=replay_multiframe(dataset,('day','30m','5m'),decision_times[:3],volume_tolerance=0)
    final,full=replay_multiframe(dataset,('day','30m','5m'),decision_times,volume_tolerance=0)
    if early!=[e for e in full if e['observed_at']<=decision_times[2]]:raise AssertionError('multiframe future rewrote scheduled event prefix')
    result={'status':'pass','cutoff':cutoff,'real_stocks_checked':checks,'duplicate_input_regression':duplicate_checks,
            'single_series_causality':{'short_bars':500,'long_bars':600,'short_events':len(short_events),'long_events':len(long_events),
                                       'prefix_unchanged':True,'direct_vs_replay_cutoffs':[150,300,500,600]},
            'observed_5m_exact_aggregation':{'state':derived['state'],'volume_tolerance':0,
                                           'parent_counts':[p['matched_parent_bars'] for p in derived['pairs']]},
            'multiframe_reference_schedule':{'decision_closes':decision_times,'events':len(full),'prefix_unchanged':True,
                                             'scope':'five daily closes selected explicitly; not a claim of full minute-by-minute replay'},
            'elapsed_seconds':round(time.monotonic()-started,3),
            'claims':{'declared_profile_predicates_checked':True,'universal_original_equivalence_proven':False,'execution_allowed':False}}
    atomic_json(out/'real-validation.json',result)
    print(json.dumps({'status':'pass','stocks':len(checks),'seconds':result['elapsed_seconds'],'prefix_events':len(short_events)},ensure_ascii=False))


if __name__=='__main__':main()
