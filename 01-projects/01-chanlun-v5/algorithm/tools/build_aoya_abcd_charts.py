"""Extend all saved TradingView layers with two ABCD schemes and causal results."""
from collections import OrderedDict,Counter
from dataclasses import replace
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from chanmodel.model import Candle,load_csv
from chanmodel.tdx_data import CN,atomic_json
from chanmodel.causal_replay import abcd_objects,PROFILE
from chanmodel.complete_study import analyze_complete
from workbench.history import build_panel,five_day,LABELS,bucket_end
from tools.run_aoya_confirmed_backtest import forward_adjust,ACTIONS

OUT=ROOT/'runs/aoya-backtest-abcd-20261108';OLD=ROOT/'runs/aoya-independent-20261108';FULL=ROOT/'runs/aoya-complete-layers-20261108'


def save_panel(p):
    atomic_json(OUT/'panels'/f'{p["period"]}.json',p)
    (OUT/'panels'/f'{p["period"]}.js').write_text('window.PANEL='+json.dumps(p,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')


def aggregate(bars,period):
    if period=='5d':return five_day(bars)
    groups=OrderedDict()
    for b in bars:
        dt=datetime.fromisoformat(b.closed_at)
        key=(dt.isocalendar().year,dt.isocalendar().week) if period=='week' else (dt.year,dt.month) if period=='month' else (dt.year,(dt.month-1)//3+1) if period=='quarter' else dt.year
        groups.setdefault(key,[]).append(b)
    cutoff=datetime.fromisoformat(bars[-1].closed_at).replace(hour=23,minute=59)
    result=[]
    for part in groups.values():
        end=datetime.fromisoformat(part[-1].closed_at);closed=bucket_end(end,period)<=cutoff
        result.append(Candle(len(result),part[0].open,max(x.high for x in part),min(x.low for x in part),part[-1].close,
                             part[-1].closed_at,sum(x.volume for x in part),closed))
    return tuple(result)


def calendar_panel(period,bars,raw_last):
    digest=hashlib.sha256(json.dumps([[x.closed_at,x.open,x.high,x.low,x.close,x.volume] for x in bars]).encode()).hexdigest()
    report=analyze_complete('sz300949',period,bars,'2026-11-08T00:00:00+08:00',digest)
    p=build_panel(period,bars,report,digest,'因果后复权日线聚合' if period!='auction' else '因果后复权09:25实际成交序列')
    p.update(kind='candles',label=LABELS[period],profile=PROFILE,definition_mode='structure_proxy' if period=='auction' else 'declared_recursive_profile',
             as_of=bars[-1].closed_at,all_centers=[dict(c,view='operating') for l in report['hierarchy']['levels'] for c in l['centers']],
             partition_centers=[dict(c,view='partition') for l in report['hierarchy']['levels'] for c in l['partition_centers']],
             merged=report['base']['merged'],fractals=report['base']['fractals'],loose_strokes=report['loose_stroke_comparison'],features=report['feature_sequences'],
             decompositions=report['decompositions'],center_evolution=report['center_evolution'],monitors=report['center_monitors'],constructions=report['construction_phases'],
             divergences=report['divergence_comparisons'],signals=report['signals'],hierarchy=report['hierarchy'],hierarchy_edges=report['hierarchy']['edges'],
             layer_catalog=report['layer_catalog'],approximation_loss=report['approximation_loss'],
             macd=[dict(time=p['bars'][i]['time'],**h) for i,h in enumerate(report['macd'])],default_visible=min(len(bars),520),execution_allowed=False,
             signal_counts={k:sum(s['class']==k for s in report['signals']) for k in ['first_buy','second_buy','third_buy','first_sell','second_sell','third_sell']},
             abcd=abcd_objects(report),confirmations=[],confirmation_records=[],signal_events=[],portfolio_metrics=None,portfolio_trades=[],portfolio_equity=[],
             raw_last_price=raw_last,analysis_last_price=bars[-1].close,adjustment_note='由逐日因果后复权价格聚合，跨除权月份不整体乘单一因子',
             backtest_scope_note='本周期只显示结构与ABCD；成交回测执行在日/60m/30m/15m/5m/1m六个周期。',
             multi_links=[],nesting=[],small_to_large=[],pair_contracts=[],revision_ledger={'events':[]})
    save_panel(p)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    summaries=json.loads((OUT/'backtest-summary.json').read_text(encoding='utf-8'))
    raw,_=load_csv(OLD/'csv/day.csv');raw=[replace(b,closed_at=datetime.fromisoformat(b.closed_at).astimezone(CN).isoformat()) for b in raw]
    bars=forward_adjust(raw)
    for period in ['5d','week','month','quarter','year']:calendar_panel(period,aggregate(bars,period),raw[-1].close)
    a=json.loads((OLD/'auction-bars.json').read_text(encoding='utf-8'));candles=[Candle(i,x['open'],x['high'],x['low'],x['close'],x['closed_at'],x['volume']) for i,x in enumerate(a)]
    calendar_panel('auction',forward_adjust(candles),candles[-1].close)
    for period in ['timeshare','five_days','timeshare_first']:
        p=json.loads((FULL/'panels'/f'{period}.json').read_text(encoding='utf-8'));p.update(abcd=[],confirmations=[],portfolio_metrics=None,portfolio_trades=[],portfolio_equity=[])
        save_panel(p)
    old=json.loads((FULL/'run-summary.json').read_text(encoding='utf-8'))
    run={'name':'奥雅股份','symbol':'sz300949','profile':PROFILE,'last_data_at':raw[-1].closed_at,'price':raw[-1].close,
         'analysis_last_price':bars[-1].close,'catalog':old['catalog'],'backtests':summaries,
         'corporate_actions':ACTIONS,'actual_replayed_bars':sum(x['bars'] for x in summaries),
         'confirmation_count':sum(x['confirmed'] for x in summaries),'strict_original_equivalence_proven':False,'execution_allowed':False}
    atomic_json(OUT/'run-summary.json',run)
    (OUT/'run-info.js').write_text('window.RUN='+json.dumps(run,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    atomic_json(OUT/'corporate-actions.json',{'actions':ACTIONS,'response_hashes':{n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['dividend-source-response.json','corporate-actions-sina.html']},
        'sources_agree':True,'adjustment':'multiply post-ex-date prices by cumulative split ratio; do not rewrite earlier bars',
        'volume':'shares as actually observed, not adjusted','portfolio':'execute raw prices, credit shares on ex-date','pre2026':'Sina table shows no distributions 2021..2025'})
    print(json.dumps({'chart_panels':len(run['catalog']),'replayed_bars':run['actual_replayed_bars'],'confirmed':run['confirmation_count'],'raw_price':run['price'],'analysis_price':run['analysis_last_price']},ensure_ascii=False))


if __name__=='__main__':main()
