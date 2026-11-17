#!/usr/bin/env python3
"""Portable feature-sequence + recursive-type chart computation under a fixed profile."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'engine'))
from chanmodel.model import Candle, Config
from chanmodel.signals import macd
from chanmodel.v2.engine import analyze
from chanmodel.v2.io import load_series
from chanmodel.v2.series import Series, session_closes
from chanmodel.complete_study import analyze_complete

CONFIG = Config(stroke_mode='strict', second_policy='conservative', max_depth=3)
PROFILE = {
    'profile_id':'course_feature_sequence_recursive_v2',
    'stroke_mode':'strict', 'second_policy':'conservative', 'third_boundary':'strict_outside',
    'segment_rule':'feature_no_gap / feature_gap_second_sequence / documented_first_pen_break',
    'base_boundary':'L0 confirmed segments at selected data resolution',
    'decomposition':'same_level_completed_center_cut_v1',
    'turn_confirmation':'opposite_center_break_completion_v1',
    'rank_is_not_timeframe':True,
    'strict_original_equivalence_proven':False,
    'execution_allowed':False,
}


def demo_series() -> Series:
    major = [140,105,128,110,145,132,158,142,151,121,140,112,134,101,123,98,119,104,142,125,156]
    major += [142,111,133,116,149,135,162,145,155,124,144,115,138,105,127,102,124,109,147,130,160]
    turns = [float(major[0])]
    for a,b in zip(major,major[1:]):
        d=b-a
        turns += [a+.8*d,a+.65*d,float(b)]
    values=[130.,132.,134.,136.,138.,turns[0]]
    for a,b in zip(turns,turns[1:]):
        values += [a+(b-a)*j/5 for j in range(1,6)]
    values += [values[-1]-.4*j for j in range(1,13)]
    times=[];day=date(2026,1,5)
    while len(times)<len(values):
        if day.weekday()<5: times += session_closes(day,'5m')
        day+=timedelta(days=1)
    bars=tuple(Candle(i,round(v-.06,6),round(v+.18,6),round(v-.18,6),round(v+.05,6),
                      times[i].isoformat(),1000.+i%23*50,True) for i,v in enumerate(values))
    return Series('sz000001','5m','unadjusted',bars,'synthetic_teaching')


def source_bytes(series:Series) -> bytes:
    stream=io.StringIO(newline='');writer=csv.writer(stream,lineterminator='\n')
    writer.writerow(['closed_at','open','high','low','close','volume','is_closed'])
    for b in series.bars:writer.writerow([b.closed_at,b.open,b.high,b.low,b.close,b.volume,1 if b.closed else 0])
    return stream.getvalue().encode('utf-8')


def adapted_fractal(f):
    return {**f,'source_index':f['source'],'index':f['merged_index'],
            'confirmed_at':f['basis_at'] if f['state']=='closed_basis' else None,
            'available_at':f['basis_at'],'definition_mode':'documented_strict_fractal',
            'source_range':[f['group_start'],f['group_end']]}


def adapted_movement(m,kind):
    confirmed=m['state']=='confirmed'
    return {**m,'finalized':confirmed,'confirmed_at':m['basis_at'] if confirmed else None,
            'available_at':m['basis_at'],'source_range':[m['start'],m['end']],
            'structure_kind':kind}


def adapted_center(c):
    return {**c,'components':c['member_ids'],'confirmed_at':c['formed_at'],
            'source_range':[c['start'],c['end']],
            'definition_mode':'recursive_completed_types' if c['rank']>1 else 'declared_base_segment_center'}


def adapted_signal(s):
    return {**s,'signal_class':s['class']+'_candidate','native_class':s['class'],
            'signal_id':s['id'],'status':'invalidated' if s['state']=='invalidated' else 'candidate',
            'definition_mode':'structure_gated_recursive_candidate',
            'confirmed_at':s['available_at'],'source_range':s['terminal_range'],
            'lower_level_trigger':'missing','execution_allowed':False}


def pack_payload(payload):
    """Intern immutable structure records; browser restores actual snapshots.

    This changes storage only, never the prefix calculations or object values.
    Identical structure versions can share memory without sharing future state.
    """
    arena=[];ids={};frames=[]
    list_fields={'fractals','raw_fractals','strokes','segments','centers','types',
                 'comparisons','native_signals','signal_candidates','events'}
    object_fields={'hierarchy','certificate_audit','signal_states'}
    def ref(value):
        encoded=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        if encoded not in ids:
            ids[encoded]=len(arena);arena.append(value)
        return ids[encoded]
    for snapshot in payload['snapshots']:
        frame={key:value for key,value in snapshot.items() if key not in list_fields|object_fields}
        frame['_lists']={key:[ref(obj) for obj in snapshot.get(key,[])] for key in list_fields}
        frame['_objects']={key:ref(snapshot[key]) for key in object_fields if key in snapshot}
        frames.append(frame)
    packed={key:value for key,value in payload.items() if key!='snapshots'}
    packed.update(arena=arena,frames=frames)
    return packed


def javascript_payload(payload):
    encoded=json.dumps(pack_payload(payload),ensure_ascii=False,separators=(',',':'),allow_nan=False)
    return ('(()=>{const p='+encoded+';const a=p.arena;p.snapshots=p.frames.map(f=>{const s={...f};'
            'for(const [k,v] of Object.entries(f._lists))s[k]=v.map(i=>a[i]);'
            'for(const [k,v] of Object.entries(f._objects))s[k]=a[v];'
            'delete s._lists;delete s._objects;return s;});delete p.arena;delete p.frames;window.CHAN_DATA=p;})();\n')


def make_payload(series:Series,raw:bytes|None=None,max_rank=3,progress=False):
    if not series.bars:raise ValueError('no bars to compute')
    raw=raw or source_bytes(series);all_events=[];registry={};states={};snapshots=[];report=None
    for i,bar in enumerate(series.bars):
        if not bar.closed:break
        report=analyze(series,bar.closed_at,CONFIG,max_rank)
        base=report['base'];hierarchy=report['hierarchy'];local_events=[]
        present=set()
        adapted=[adapted_signal(s) for s in report['signals']]
        for signal in adapted:
            key=signal['id'];present.add(key);previous=registry.get(key)
            if previous is None:
                event={**signal,'event':'first_seen','native_event':'appeared','observed_at':bar.closed_at,
                       'observed_index':i,'available_at':i,'basis_available_at':signal['available_at'],
                       'revision':0,'exec_not_before':i+1}
                local_events.append(event);registry[key]={'active':True,'value':copy.deepcopy(signal),'revision':0}
            elif not previous['active'] or previous['value']!=signal:
                revision=previous['revision']+1
                event_kind='invalidated' if signal['status']=='invalidated' and previous['value']['status']!='invalidated' else 'revised'
                local_events.append({**signal,'event':event_kind,'native_event':event_kind,
                                     'observed_at':bar.closed_at,'observed_index':i,
                                     'available_at':i,'basis_available_at':signal['available_at'],'revision':revision})
                registry[key]={'active':True,'value':copy.deepcopy(signal),'revision':revision}
            states[key]=signal['status']
        for key,previous in registry.items():
            if previous['active'] and key not in present:
                previous['active']=False;previous['revision']+=1;states[key]='withdrawn'
                local_events.append({'event':'withdrawn','native_event':'withdrawn','signal_id':key,'id':key,
                                     'observed_at':bar.closed_at,'observed_index':i,'available_at':i,
                                     'revision':previous['revision'],'reason':'candidate absent after current-prefix structural recalculation'})
        all_events.extend(local_events)
        centers=[adapted_center(c) for layer in hierarchy['levels'] for c in layer['centers']]
        types=[u for layer in hierarchy['levels'] for u in layer['completed_types']]
        rank1=hierarchy['levels'][0] if hierarchy['levels'] else None
        state='untradable_unclear'
        if centers:state='center_oscillation'
        if rank1 and rank1['movement_views']['completed_types']:
            latest=rank1['movement_views']['completed_types'][-1]
            if latest['kind']=='trend':state=latest['direction']+'trend_under_profile'
        snapshots.append({'as_of':i,'as_of_time':bar.closed_at,'input_bars':i+1,
                          'merged_count':len(base['merged']),
                          'fractals':[adapted_fractal(f) for f in base['fractals']],
                          'raw_fractals':[adapted_fractal(f) for f in base['fractals']],
                          'strokes':[adapted_movement(m,'stroke') for m in base['strokes']],
                          'segments':[adapted_movement(m,'segment') for m in base['segments']],
                          'centers':centers,'types':types,'hierarchy':hierarchy,
                          'certificate_audit':report['certificate_audit'],
                          'comparisons':report['divergence_comparisons'],'native_signals':report['signals'],
                          'signal_candidates':adapted,'signal_states':dict(states),'events':local_events,
                          'current_state':state,'definition_mode':report['definition_mode'],
                          'strict_original_equivalence_proven':False,'execution_allowed':False})
        if progress and (i+1)%100==0:print(f'prefix={i+1}/{len(series.bars)}',flush=True)
    histogram=macd(list(series.bars[:len(snapshots)]),CONFIG)
    complete=analyze_complete(series.symbol,series.period,series.bars,series.bars[len(snapshots)-1].closed_at,
                              hashlib.sha256(raw).hexdigest(),source=series.source,
                              adjustment=series.adjustment,config=CONFIG,max_rank=max_rank)
    meta={'synthetic':series.source=='synthetic_teaching','dataset_label':'合成教学数据' if series.source=='synthetic_teaching' else '用户CSV',
          'symbol':series.symbol,'level':series.period,'trade_level':series.period,
          'adjustment':series.adjustment,'source':series.source,
          'definition_mode':'recursive_completed_types_under_same_level_decomposition',
          'engine_mode':'recursive_profile_v2','structure_completeness':'fixed_profile_implemented',
          'input_sha256':hashlib.sha256(raw).hexdigest(),'as_of':len(snapshots)-1,
          'engine_sha256':hashlib.sha256((HERE/'engine/chanmodel/v2/engine.py').read_bytes()).hexdigest(),
          'rules':PROFILE,'max_rank':max_rank,'strict_original_equivalence_proven':False,'execution_allowed':False,
          'implemented':['strict_strokes','feature_sequence_segments','gap_second_sequence',
                         'completed_type_recursion','recursive_center_certificates','same_level_decomposition',
                         'six_structure_gated_signal_classes','causal_version_ledger','timestamped_multiframe_api'],
          'approximation_loss':complete['approximation_loss'],
          'timeline_policy':'Every prefix invokes V2 analyze at the literal bar close; observed versions are never backdated.',
          'timestamp_policy':'explicit CN_A exchange-session close timestamps; synthetic weekdays are illustrative, not a holiday calendar',
          'counts':{k:len(snapshots[-1][k]) for k in ['fractals','strokes','segments','centers','types','signal_candidates']}}
    payload={'meta':meta,'bars':[{'index':b.pos,'time':b.closed_at,'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in series.bars[:len(snapshots)]],
             'snapshots':snapshots,'macd':[h['histogram'] for h in histogram],
             'macd_components':histogram,'events':all_events,
             'full_layers':{key:complete[key] for key in ['feature_sequences','center_evolution','center_monitors',
                                                       'construction_phases','decompositions','layer_catalog']}}
    return payload,complete


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path)
    parser.add_argument('--symbol',default='sz000001')
    parser.add_argument('--period',default='5m',choices=['1m','5m','15m','30m','60m','day'])
    parser.add_argument('--max-rank',type=int,default=3)
    parser.add_argument('--output',type=Path,default=HERE/'data.js')
    args=parser.parse_args()
    if args.csv:
        series,receipt=load_series(args.csv,args.symbol,args.period,'unadjusted','user_csv')
        raw=args.csv.read_bytes()
    else:
        series=demo_series();raw=source_bytes(series);(HERE/'demo_ohlc.csv').write_bytes(raw)
    payload,report=make_payload(series,raw,args.max_rank,True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(javascript_payload(payload),encoding='utf-8')
    (args.output.parent/'full_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (args.output.parent/'RULE_PROFILE.json').write_text(json.dumps(PROFILE,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'bars':len(payload['bars']),'counts':payload['meta']['counts'],
                      'ranks':[(x['rank'],len(x['completed_types']),len(x['centers'])) for x in report['hierarchy']['levels']],
                      'certificate_audit':report['certificate_audit'],'output':str(args.output),'bytes':args.output.stat().st_size},ensure_ascii=False))


if __name__=='__main__':main()
