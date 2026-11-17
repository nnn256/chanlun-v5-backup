"""Recompute user chart objects with the pinned engine; preserve old artifacts."""
from collections import OrderedDict
from concurrent.futures import Future
import gzip
import hashlib
import json
import threading

from chanmodel.reference_engine import analyze_reference,PROFILE,COMMIT,SETTINGS
from chanmodel.kline_audit import candles_from_panel,audit_panel
from chanmodel.signal_chart import attach_chart_annotations,candidate_counts,is_active_candidate
from chanmodel.tdx_data import atomic_bytes
from .store import STATE

CACHE=OrderedDict();LOCK=threading.RLock()
FLIGHTS={}
ADAPTER_VERSION='native-context-review-v7'
MAX_CACHE_BYTES=24*1024*1024
MAX_ENTRY_BYTES=12*1024*1024


def _report_bytes(key,path,build):
    with LOCK:
        cached=CACHE.get(key)
        if cached is not None:
            CACHE.move_to_end(key)
            return cached
        pending=FLIGHTS.get(key)
        owner=pending is None
        if owner:
            pending=Future();FLIGHTS[key]=pending
    if not owner:return pending.result()
    try:
        if path.exists():
            raw=gzip.decompress(path.read_bytes())
            value=json.loads(raw)
            if value.get('engine_commit')!=COMMIT or value.get('input_sha256')!=key:
                raise ValueError('reference rebuild cache identity mismatch')
        else:
            # analyze_reference returns geometry-reviewed structures. Retain that
            # result once; callers always decode an isolated object below.
            value=build()
            raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
            atomic_bytes(path,gzip.compress(raw,compresslevel=3,mtime=0))
        with LOCK:
            if len(raw)<=min(MAX_ENTRY_BYTES,MAX_CACHE_BYTES):
                CACHE[key]=raw;CACHE.move_to_end(key)
                while len(CACHE)>8 or sum(map(len,CACHE.values()))>MAX_CACHE_BYTES:
                    CACHE.popitem(last=False)
        pending.set_result(raw)
        return raw
    except BaseException as exc:
        pending.set_exception(exc)
        raise
    finally:
        with LOCK:
            if FLIGHTS.get(key) is pending:FLIGHTS.pop(key,None)


def reference_report(symbol,period,bars,cutoff,adjustment='unadjusted',source='saved_raw_ohlcv'):
    payload={'adapter_version':ADAPTER_VERSION,'symbol':symbol,'period':period,'source':source,'adjustment':adjustment,'cutoff':cutoff,'commit':COMMIT,'settings':SETTINGS,
             'bars':[[b.pos,b.closed_at,b.open,b.high,b.low,b.close,b.volume,b.closed] for b in bars]}
    key=hashlib.sha256(json.dumps(payload,allow_nan=False,separators=(',',':')).encode()).hexdigest()
    path=STATE/'reference-rebuild'/COMMIT[:12]/(key+'.json.gz')
    raw=_report_bytes(key,path,lambda:analyze_reference(symbol,period,bars,cutoff,key,source,adjustment))
    return json.loads(raw)


def rebuild_bundle(bundle):
    symbol=bundle['summary']['symbol'];chart=bundle['chart'];cutoff=chart.get('as_of',bundle['summary']['as_of'])
    evidence=bundle.setdefault('evidence',{});new_reports={}
    for panel in chart['panels']:
        if panel.get('kind')=='line':continue
        audit=audit_panel(panel);panel['kline_audit']=audit
        if audit['state']=='invalid':
            panel.update(strokes=[],segments=[],centers=[],signals=[],all_signals=[],structure_layers=[]);continue
        previous={'strokes':len(panel.get('strokes',[])),'segments':len(panel.get('segments',[])),
                  'signals':len(panel.get('all_signals',panel.get('signals',[])))}
        bars=candles_from_panel(panel)
        report=reference_report(symbol,panel['period'],bars,cutoff,bundle['summary'].get('adjustment','unadjusted'))
        new_reports[panel['period']]=report
        panel.update(merged=report['base']['merged'],fractals=report['base']['fractals'],
                     strokes=report['base']['strokes'],segments=report['base']['segments'],higher_segments=report['base']['higher_segments'],
                     structure_layers=report['hierarchy']['levels'],all_signals=report['signals'],
                     centers=report['hierarchy']['levels'][0]['centers'],
                     signals=[s for s in report['signals'] if s['rank']==1],
                     complete_evidence={'divergence_comparisons':[]},engine=PROFILE,
                     engine_provenance=report['engine_provenance'],native_scope_names={'1':'笔结构','2':'线段结构'},
                     reference_comparison={'saved':previous,'rebuilt':{'strokes':len(report['base']['strokes']),
                                            'segments':len(report['base']['segments']),'signals':len(report['signals'])},
                                           'semantics':'independently recomputed from all original candles; original task bytes unchanged'},
                     geometry_review=report['geometry_review'],
                     note='固定引擎 · 笔/线段分别标注 · 橙色待复核不作确认')
        for period_summary in [bundle['summary'].get('periods',{}).get(panel['period'])]:
            if period_summary is not None:
                period_summary['active_candidates']=[{**s,'anchor_time':s['event_time'],
                            'available_time':s['available_time']} for s in report['signals'] if is_active_candidate(s)]
                bundle['summary'].setdefault('period_candidate_counts',{})[panel['period']]=candidate_counts(report['signals'])
    if 'day' in bundle['summary'].get('periods',{}):
        bundle['summary']['active_candidates']=len(bundle['summary']['periods']['day'].get('active_candidates',[]))
    evidence['reference_reports']=new_reports
    bundle['summary'].update(display_engine=PROFILE,display_engine_commit=COMMIT,
                             result_text='已按固定特征序列引擎从完整原始K线重建；原任务与旧回测保持其原版本')
    chart.update(display_engine=PROFILE,engine_commit=COMMIT,
                 approximation_loss=['native stroke/segment scope is not calendar timeframe or universal theoretical rank',
                                     'engine local structure completion is not an independently proven multi-timeframe execution trigger'])
    attach_chart_annotations(chart)
    return bundle
