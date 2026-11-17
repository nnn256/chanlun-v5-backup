"""Replay every available closed bar; audited confirmation and executable fills."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from dataclasses import replace
from datetime import datetime
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from chanmodel.model import load_csv,Candle
from chanmodel.causal_replay import StreamingStructure,SignalLedger,abcd_objects,PROFILE,CONFIG
from chanmodel.causal_portfolio import simulate,CostModel
from chanmodel.structure import merge_bars,fractals_at,strokes_at
from chanmodel.segments import build_segments
from chanmodel.tdx_data import atomic_json,atomic_bytes,now_iso
from chanmodel.complete_study import analyze_complete
from workbench.history import build_panel

OLD=ROOT/'runs/aoya-independent-20261108';FULL=ROOT/'runs/aoya-complete-layers-20261108'
OUT=ROOT/'runs/aoya-backtest-abcd-20261108'
PERIODS=['day','60m','30m','15m','5m','1m']
ACTIONS=[{'ex_date':'2026-05-29','record_date':'2026-05-28','public_notice_date':'2026-05-22',
          'share_multiplier':1.45,'cash_per_share':0,'description':'每10股转增4.5股',
          'sources':['dividend-source-response.json','corporate-actions-sina.html']}]


def sha(raw):return hashlib.sha256(raw).hexdigest()
def savegz(path,obj):atomic_bytes(path,gzip.compress(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),compresslevel=3,mtime=0))


def forward_adjust(raw):
    adjusted=[]
    for b in raw:
        factor=1.
        for a in ACTIONS:
            if b.closed_at[:10]>=a['ex_date']:factor*=a['share_multiplier']
        adjusted.append(replace(b,open=round(b.open*factor,8),high=round(b.high*factor,8),low=round(b.low*factor,8),close=round(b.close*factor,8)))
    return adjusted


def run_period(period):
    started=time.monotonic();path=OLD/'csv'/f'{period}.csv';raw,meta=load_csv(path)
    raw=[b for b in raw if b.closed]
    # Preserve exchange-local dates after the generic loader normalizes UTC.
    from chanmodel.tdx_data import CN
    raw=[replace(b,closed_at=datetime.fromisoformat(b.closed_at).astimezone(CN).isoformat()) for b in raw]
    adjusted=forward_adjust(raw);stream=StreamingStructure();ledger=SignalLedger(period);audit_samples=[]
    input_hash=sha(path.read_bytes());target=OUT/period;target.mkdir(parents=True,exist_ok=True)
    proof_times={0,len(raw)-1,len(raw)//3,2*len(raw)//3}
    prev_snapshot=None
    for i,bar in enumerate(adjusted):
        changed=stream.append(bar);ledger.invalidate(bar)
        if changed:
            report=stream.snapshot();ledger.observe(report,bar,stream.bars);prev_snapshot=report
        if i in proof_times:
            merged=merge_bars(adjusted[:i+1],CONFIG);fracs=fractals_at(merged);strokes,_=strokes_at(fracs,CONFIG);segments=build_segments(strokes)
            same=stream.merged==merged and stream.fractals==fracs and stream.strokes==strokes and len(segments)==len(stream.segments) and all({k:a[k] for k in b}==b for a,b in zip(stream.segments,segments))
            if not same:raise ValueError('Incremental/batch equivalence failed at '+period+':'+str(i))
            audit_samples.append({'index':i,'closed_at':bar.closed_at,'batch_prefix_equivalent':True})
        if i%1000==0 or i==len(raw)-1:
            atomic_json(target/'progress.json',{'period':period,'done':i+1,'total':len(raw),
                'confirmed':len(ledger.confirmations),'seen':len(ledger.records),'structure_rebuilds':stream.structure_rebuilds,
                'elapsed_seconds':round(time.monotonic()-started,1)})
    final=stream.snapshot();clauses=abcd_objects(final)
    d_raw,_=load_csv(OLD/'csv/day.csv');daily={datetime.fromisoformat(b.closed_at).astimezone(CN).date().isoformat():b.close for b in d_raw}
    portfolio=simulate(raw,adjusted,ledger.events,daily,ACTIONS,period=period)
    delayed_events=[{**e,'observed_index':e['observed_index']+1,'observed_at':adjusted[e['observed_index']+1].closed_at}
                    for e in ledger.events if e['observed_index']+1<len(adjusted)]
    delay=simulate(raw,adjusted,delayed_events,daily,ACTIONS,period=period)
    expensive=simulate(raw,adjusted,ledger.events,daily,ACTIONS,replace(CostModel(),slippage_bps=10),period=period)
    # Same confirmation stream, two deterministic sensitivity checks; no tuning.
    sensitivities={'base':portfolio['metrics'],'one_bar_extra_latency':delay['metrics'],'ten_bps_slippage':expensive['metrics']}
    # Audit every original-rule gate at first observation and at confirmation.
    records=list(ledger.records.values())
    for rec in records:
        rec['current_state']=rec['state'];rec['definition_mode']='source_clause_confirmed_under_declared_base' if rec['confirmed_at'] else 'unconfirmed_or_proxy'
    history={'period':period,'profile':PROFILE,'input_sha256':input_hash,'bars_replayed':len(raw),'first':raw[0].closed_at,'last':raw[-1].closed_at,
             'adjustment':'causal_forward_split_adjusted','corporate_actions':ACTIONS,'event_count':len(ledger.events),
             'events':ledger.events,'confirmations':ledger.confirmations,'records':records,
             'prefix_validation':audit_samples,'stream_stats':{'structure_rebuilds':stream.structure_rebuilds,'segment_rebuilds':stream.segment_rebuilds,
                'stroke_rebuilds':stream.stroke_rebuilds,'each_closed_bar_processed':True},'future_data_used_for_confirmation':False,
             'strict_original_equivalence_proven':False,'execution_allowed':False}
    savegz(target/'signal-ledger.json.gz',history);savegz(target/'portfolio.json.gz',portfolio);savegz(target/'final-structure.json.gz',final)
    atomic_json(target/'abcd.json',clauses);atomic_json(target/'sensitivity.json',sensitivities)
    for name,rows in [('events',ledger.events),('trades',portfolio['trades']),('equity',portfolio['equity']),('confirmations',ledger.confirmations)]:
        # JSONL preserves nested certificates without CSV string ambiguity.
        atomic_bytes(target/f'{name}.jsonl.gz',gzip.compress(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows).encode(),mtime=0))
    confirmation_keys=['period','signal_id','class','rank','side','anchor_time','observed_at','confirmed_at','price','invalidation','definition_mode']
    with (target/'confirmed-signals.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=confirmation_keys,extrasaction='ignore');writer.writeheader();writer.writerows(ledger.confirmations)
    with (target/'trades.csv').open('w',newline='',encoding='utf-8-sig') as f:
        keys=['signal_id','class','rank','signal_time','entry_time','entry_price','initial_shares','entry_fees','exit_time','exit_price','exit_fees','exit_reason','net_profit','net_return','holding_sessions']
        writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(portfolio['trades'])
    full=analyze_complete('sz300949',period,adjusted,adjusted[-1].closed_at,input_hash)
    panel=build_panel(period,adjusted,full,input_hash,'原始TDX价格按已发生转增做因果后复权')
    old_panel=json.loads((FULL/'panels'/f'{period}.json').read_text(encoding='utf-8'))
    # Rebuild all geometry on the adjusted series; no unadjusted lines over it.
    panel.update(kind='candles',profile=PROFILE,definition_mode='source_clause_gated_replay',as_of=raw[-1].closed_at,
                 all_centers=[dict(c,view='operating') for l in full['hierarchy']['levels'] for c in l['centers']],
                 partition_centers=[dict(c,view='partition') for l in full['hierarchy']['levels'] for c in l['partition_centers']],
                 merged=full['base']['merged'],fractals=full['base']['fractals'],loose_strokes=full['loose_stroke_comparison'],features=full['feature_sequences'],
                 decompositions=full['decompositions'],center_evolution=full['center_evolution'],monitors=full['center_monitors'],constructions=full['construction_phases'],
                 divergences=full['divergence_comparisons'],signals=[{**p,'event_time':adjusted[p['anchor']].closed_at,
                    'available_time':adjusted[p['available_at']].closed_at,'policy':'original_101_force_evidence' if p.get('retest_mode')=='weak_retest_101' else 'standard_structure'} for p in final['signals']],hierarchy=full['hierarchy'],hierarchy_edges=full['hierarchy']['edges'],
                 layer_catalog=full['layer_catalog'],approximation_loss=full['approximation_loss'],
                 macd=[dict(time=panel['bars'][i]['time'],**h) for i,h in enumerate(full['macd'])],
                 default_visible=min(len(raw),520),execution_allowed=False,
                 signal_counts={k:sum(p['class']==k for p in full['signals']) for k in old_panel['signal_counts']},
                 confirmations=ledger.confirmations,confirmation_records=records,signal_events=ledger.events,abcd=clauses,
                 portfolio_metrics=portfolio['metrics'],portfolio_trades=portfolio['trades'],portfolio_equity=portfolio['equity'],
                 raw_last_price=raw[-1].close,analysis_last_price=adjusted[-1].close,
                 adjustment_note='因果后复权：2026-05-29起价格×1.45；回测按原始成交价与实际转增股数记账',
                 multi_links=[],nesting=[],small_to_large=[],pair_contracts=[],revision_ledger={'events':[]})
    atomic_json(OUT/'panels'/f'{period}.json',panel)
    (OUT/'panels'/f'{period}.js').write_text('window.PANEL='+json.dumps(panel,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    summary={'period':period,'bars':len(raw),'first':raw[0].closed_at,'last':raw[-1].closed_at,'candidates_seen':len(records),
             'confirmed':len(ledger.confirmations),'confirmed_by_class':{k:sum(e['class']==k for e in ledger.confirmations) for k in old_panel['signal_counts']},
             'confirmed_by_rank':{str(n):sum(e['rank']==n for e in ledger.confirmations) for n in range(1,9)},
             'final_states':{k:sum(r['state']==k for r in records) for k in ['candidate','confirmed','invalidated','withdrawn']},
             'metrics':portfolio['metrics'],'sensitivities':sensitivities,'prefix_validation':audit_samples,
             'input_sha256':input_hash,'elapsed_seconds':round(time.monotonic()-started,2),'status':'complete'}
    atomic_json(target/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True);return summary


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--period',choices=PERIODS);parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args();sys.stdout.reconfigure(encoding='utf-8');(OUT/'panels').mkdir(parents=True,exist_ok=True)
    if args.period:run_period(args.period);return
    atomic_json(OUT/'settings.json',{'created_at':now_iso(),'symbol':'sz300949','periods':PERIODS,'profile':PROFILE,'corporate_actions':ACTIONS,
        'confirmation':'original clause gates + completed opposite child boundary, observed on each closed-bar prefix',
        'portfolio':CostModel().__dict__,'event_backfill_forbidden':True,
        'known_limitations':['finite declared L0 segment convention','historical vendor revisions not recoverable','single-stock in-sample research'],
        'execution_allowed':False})
    summaries=[]
    with ProcessPoolExecutor(max_workers=max(1,min(args.workers,3))) as pool:
        futures={pool.submit(run_period,p):p for p in PERIODS}
        for future in as_completed(futures):
            summaries.append(future.result());atomic_json(OUT/'backtest-summary.json',sorted(summaries,key=lambda x:PERIODS.index(x['period'])))
    print(json.dumps({'complete':True,'periods':len(summaries),'confirmed':sum(r['confirmed'] for r in summaries),'trades':sum(r['metrics']['completed_trades'] for r in summaries)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
